"""Server-side stream cadence: when Sunshine starts sending each video frame (outgoing UDP from port 47998).
Run as root. Usage: framesniff.py IFACE SECONDS"""
import collections, socket, struct, sys, time
iface, secs = sys.argv[1], float(sys.argv[2])
s = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(0x0003)); s.bind((iface, 0x0003)); s.settimeout(0.5)
first, last, size = {}, {}, collections.Counter(); end = time.monotonic() + secs
while time.monotonic() < end:
    try: data, addr = s.recvfrom(65535)
    except socket.timeout: continue
    if addr[2] != 4 or addr[1] != 0x0800: continue  # outgoing IPv4 only
    ihl = (data[0] & 15) * 4
    if data[9] != 17 or len(data) < ihl + 8 + 28: continue
    sport, dport = struct.unpack('!HH', data[ihl:ihl + 4])
    if sport != 47998: continue
    frame = struct.unpack('<I', data[ihl + 8 + 20:ihl + 8 + 24])[0]
    size[frame] += len(data)
    now = time.monotonic(); first.setdefault(frame, now); last[frame] = now
frames = sorted(first)
frames = [f for f in frames if f - frames[0] < 100000]
t = [first[f] for f in frames]; d = [(b - a) * 1000 for a, b in zip(t, t[1:])]
gaps = [b - a for a, b in zip(frames, frames[1:])]
import statistics
print(f'{len(frames)} frames in {t[-1] - t[0]:.1f} s = {len(d) / (t[-1] - t[0]):.2f} fps sent; frame index steps other than 1: {sum(1 for g in gaps if g != 1)}')
print(f'send interval ms: mean {statistics.mean(d):.2f}, stdev {statistics.pstdev(d):.2f}, min {min(d):.1f}, max {max(d):.1f}')
hist = collections.Counter(round(x) for x in d)
print('interval histogram (ms: count):', dict(sorted(hist.items())))
print('first 50 intervals:', ' '.join(f'{x:.0f}' for x in d[:50]))
print(f'mean frame size {statistics.mean(size[f] for f in frames) / 1000:.0f} kB')
rows = list(zip(d, frames[1:]))
print('gap-before(ms)/size(kB)/send-span(ms):', ' '.join('%.0f/%.0f/%.0f' % (x, size[f] / 1000, (last[f] - first[f]) * 1000) for x, f in rows[:44]))
big = [x for x, f in rows if size[f] > 15000]; small = [x for x, f in rows if size[f] <= 15000]
print('gap before a large frame: mean %.1f ms (n=%d); before a small frame: mean %.1f ms (n=%d)' % (statistics.mean(big) if big else 0, len(big), statistics.mean(small) if small else 0, len(small)))
