/* tvpace: even frame spacing for a Sunshine video stream.
 *
 * Sunshine sends each video frame the moment its encode finishes. Capture, colour
 * conversion and NVENC share the GPU with the desktop, so that moment varies by
 * several milliseconds from frame to frame and the frames leave unevenly spaced.
 * This library is preloaded into Sunshine and holds the first datagram of every
 * video frame until the frame's slot on an even grid (one slot per frame interval).
 *
 * The grid is placed just late enough that frames are ready before their slot:
 *  - a frame that misses its slot is sent at once and the grid moves back by the miss;
 *  - every TVPACE_WINDOW_S seconds, if even the tightest frame of the window had more
 *    than TVPACE_MARGIN_MS to spare, the grid is moved forward by the excess, spread
 *    over the next window (microseconds per frame).
 * The cost is added video latency of about the worst pipeline delay of the last
 * window plus the margin, never more than TVPACE_MAX_MS. Only frames that directly
 * follow the previous frame of a stream at the configured rate are ever held.
 *
 * Environment:
 *   TVPACE_PORT      local UDP port of the video socket (Sunshine `port` + 9; default 47998)
 *   TVPACE_FPS       stream frame rate (default 60); a stream at another rate passes through unpaced
 *   TVPACE_MARGIN_MS spare time kept before the slot of the tightest frame (default 3)
 *   TVPACE_WINDOW_S  length of the window the grid adapts over (default 30)
 *   TVPACE_INIT_MS   where a new stream's grid starts, after its first frame (default 20)
 *   TVPACE_MAX_MS    largest hold of one frame (default 50)
 *   TVPACE_LOG       seconds between one-line statistics on stderr (default 60, 0 = off)
 *
 * Load with the dynamic loader, because /usr/bin/sunshine carries file capabilities
 * and glibc ignores LD_PRELOAD for such programs:
 *   /usr/lib/ld-linux-x86-64.so.2 --preload /path/libtvpace.so /usr/bin/sunshine CONF
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <time.h>

#define ENC_PREFIX 32 /* Sunshine's video_packet_enc_prefix_t: iv[12], frameNumber, tag[16] */
#define RATE_WINDOW 128

static ssize_t (*real_sendmsg)(int, const struct msghdr *, int);
static int (*real_sendmmsg)(int, struct mmsghdr *, unsigned int, int);
static pthread_once_t once = PTHREAD_ONCE_INIT;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

static int port = 47998;
static int64_t interval_ns, margin_ns, init_ns, max_ns, log_ns;
static int window;          /* frames per adaptation window */

static int have_frame;      /* a frame has been seen on this socket */
static uint32_t last_frame; /* its index */
static int64_t slot;        /* release time of that frame */
static int64_t trim;        /* ns taken off every interval while the grid moves forward */
static int64_t spare_min;   /* least time to spare before a slot in the current window */
static int win_frames;
static int64_t rate_start;  /* arrival-rate check: start time and frame count of the current check */
static int rate_count;
static int on_rate = 1;     /* the stream runs at TVPACE_FPS (checked every RATE_WINDOW frames) */
static uint64_t n_frames, n_late, n_restart;
static int64_t late_max, log_spare_min = INT64_MAX, next_log;

static int64_t now_ns(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (int64_t) t.tv_sec * 1000000000 + t.tv_nsec;
}

static int64_t env_ms(const char *name, double def) {
  const char *v = getenv(name);
  return (int64_t) ((v && *v ? atof(v) : def) * 1e6);
}

static void init(void) {
  real_sendmsg = dlsym(RTLD_NEXT, "sendmsg");
  real_sendmmsg = dlsym(RTLD_NEXT, "sendmmsg");
  const char *v = getenv("TVPACE_PORT");
  if (v && *v) port = atoi(v);
  v = getenv("TVPACE_FPS");
  int fps = v && *v ? atoi(v) : 60;
  if (fps < 1) fps = 60;
  interval_ns = 1000000000 / fps; /* the same integer division as Sunshine's capture clock */
  margin_ns = env_ms("TVPACE_MARGIN_MS", 3);
  init_ns = env_ms("TVPACE_INIT_MS", 20);
  max_ns = env_ms("TVPACE_MAX_MS", 50);
  window = (int) (env_ms("TVPACE_WINDOW_S", 30) / 1000000 * fps);
  if (window < fps) window = fps;
  log_ns = env_ms("TVPACE_LOG", 60) * 1000;
  fprintf(stderr, "tvpace: video port %d, %d fps, margin %.1f ms, window %d frames, max hold %.0f ms\n", port, fps, margin_ns / 1e6, window, max_ns / 1e6);
}

/* Frame index of the first datagram in this message, or -1 if it is not a video datagram. */
static int64_t frame_of(int fd, const struct msghdr *msg) {
  struct sockaddr_storage ss;
  socklen_t len = sizeof ss;
  if (getsockname(fd, (struct sockaddr *) &ss, &len)) return -1;
  int p = ss.ss_family == AF_INET ? ntohs(((struct sockaddr_in *) &ss)->sin_port) : ss.ss_family == AF_INET6 ? ntohs(((struct sockaddr_in6 *) &ss)->sin6_port) : -1;
  if (p != port) return -1;
  uint8_t head[24];
  size_t got = 0, first_len = 0;
  for (size_t i = 0; i < msg->msg_iovlen && got < sizeof head; i++) {
    size_t n = msg->msg_iov[i].iov_len;
    if (!n) continue;
    if (!first_len) first_len = n;
    if (n > sizeof head - got) n = sizeof head - got;
    memcpy(head + got, msg->msg_iov[i].iov_base, n);
    got += n;
  }
  if (got < sizeof head) return -1;
  uint32_t frame;
  if (first_len == ENC_PREFIX) /* encrypted video: the prefix is its own buffer and carries the frame number */
    memcpy(&frame, head + 12, 4);
  else if ((head[0] & 0xc0) == 0x80) /* plain video: RTP(12) + reserved(4) + streamPacketIndex(4) + frameIndex */
    memcpy(&frame, head + 20, 4);
  else
    return -1;
  return frame;
}

static void pace(int fd, const struct msghdr *msg) {
  int64_t f = frame_of(fd, msg);
  if (f < 0) return;
  pthread_mutex_lock(&lock);
  if (have_frame && (uint32_t) f == last_frame) { /* a later batch of the same frame */
    pthread_mutex_unlock(&lock);
    return;
  }
  int64_t now = now_ns();
  int consecutive = have_frame && (uint32_t) f == last_frame + 1;
  last_frame = (uint32_t) f;
  have_frame = 1;
  if (!consecutive) {
    rate_count = 0;
    on_rate = 1;
  } else if (++rate_count == RATE_WINDOW) { /* mean arrival period within 3% of the configured one? */
    int64_t period = (now - rate_start) / RATE_WINDOW;
    on_rate = period > interval_ns * 97 / 100 && period < interval_ns * 103 / 100;
    rate_count = 0;
  }
  if (!rate_count) rate_start = now;

  int64_t release = now;
  if (!consecutive || !on_rate) { /* new stream, a gap, or not the configured rate: send now, restart the grid */
    slot = now + init_ns;
    trim = 0;
    win_frames = 0;
    n_restart += !consecutive;
  } else {
    slot += interval_ns - trim;
    if (slot - now > max_ns) slot = now + max_ns;
    int64_t spare = slot - now;
    if (spare < 0) { /* missed its slot: send now, the grid follows */
      n_late++;
      if (-spare > late_max) late_max = -spare;
      slot = now;
      spare = 0;
    }
    if (!win_frames || spare < spare_min) spare_min = spare;
    if (spare < log_spare_min) log_spare_min = spare;
    if (++win_frames == window) { /* move the grid forward by what even the tightest frame had to spare */
      trim = spare_min > margin_ns ? (spare_min - margin_ns) / window : 0;
      win_frames = 0;
    }
    release = slot;
  }
  n_frames++;
  if (log_ns && now >= next_log) {
    if (next_log) fprintf(stderr, "tvpace: %llu frames, %llu late (worst %.1f ms), least spare %.1f ms, %llu restarts%s\n", (unsigned long long) n_frames, (unsigned long long) n_late, late_max / 1e6, log_spare_min == INT64_MAX ? 0 : log_spare_min / 1e6, (unsigned long long) n_restart, on_rate ? "" : ", stream is not at the configured rate: not paced");
    n_frames = n_late = n_restart = 0;
    late_max = 0;
    log_spare_min = INT64_MAX;
    next_log = now + log_ns;
  }
  pthread_mutex_unlock(&lock);
  if (release > now) {
    struct timespec t = {release / 1000000000, release % 1000000000};
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &t, NULL)) {}
  }
}

ssize_t sendmsg(int fd, const struct msghdr *msg, int flags) {
  pthread_once(&once, init);
  pace(fd, msg);
  return real_sendmsg(fd, msg, flags);
}

int sendmmsg(int fd, struct mmsghdr *vec, unsigned int n, int flags) {
  pthread_once(&once, init);
  if (n) pace(fd, &vec[0].msg_hdr);
  return real_sendmmsg(fd, vec, n, flags);
}
