// One persistent Tiny2Lite motor owner: get, speed YAW PITCH, stop.
// Setters submit queued SDK commands; actual feedback is sampled separately.
// AI must be off before launch. Input watchdog and shutdown stop velocity.
// Physical calibration 2026-10-04: positive SDK pan speed DECREASES motor yaw;
// positive pitch speed INCREASES motor pitch. Protocol/bounds use motor axes.
#include <atomic>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdarg>
#include <iostream>
#include <memory>
#include <mutex>
#include <poll.h>
#include <sstream>
#include <string>
#include <thread>
#include <unistd.h>
#include <dev/devs.hpp>
using Clock=std::chrono::steady_clock;
static volatile sig_atomic_t shutting_down=0;
static void signal_stop(int) { shutting_down=1; }
static void quiet_log(int32_t,const char *,va_list,void *) {}
static double age(Clock::time_point at) { return std::chrono::duration<double>(Clock::now()-at).count(); }
struct Feedback {
    std::mutex mutex;
    Device::AiGimbalStateInfo state{};
    Clock::time_point at{};
    bool valid=false;
};
int main() {
    std::signal(SIGTERM,signal_stop); std::signal(SIGINT,signal_stop); std::signal(SIGPIPE,SIG_IGN);
    dev_set_log_handler(quiet_log,nullptr);
    Devices::get().setEnableMdnsScan(false);
    std::shared_ptr<Device> camera;
    const auto deadline=Clock::now()+std::chrono::seconds(6);
    while (!camera && !shutting_down) {
        for (const auto &device:Devices::get().getDevList()) {
            if (!device || device->productType()!=ObsbotProdTiny2Lite) continue;
            if (camera) { Devices::get().close(); return 3; }
            camera=device;
        }
        if (camera || Clock::now()>=deadline) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    if (!camera) { Devices::get().close(); return 4; }
    Feedback feedback;
    if (camera->aiGetGimbalStateR(&feedback.state)!=0) { Devices::get().close(); return 5; }
    feedback.valid=true; feedback.at=Clock::now();
    std::atomic<bool> running(true);
    // The only other SDK lane reads feedback; main alone writes motor commands.
    // Blocking readback cannot block the input watchdog.
    std::thread reader([&]() {
        while (running) {
            Device::AiGimbalStateInfo next{};
            int result=camera->aiGetGimbalStateR(&next);
            {
                std::lock_guard<std::mutex> guard(feedback.mutex);
                feedback.valid=result==0;
                if (result==0) { feedback.state=next; feedback.at=Clock::now(); }
            }
            for (int i=0;i<4 && running;++i) std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
    });
    double submitted_yaw=0,submitted_pitch=0;
    bool active=false;
    auto last_input=Clock::now();
    auto zero=[&]() {
        camera->aiSetGimbalStop();
        const bool accepted=camera->aiSetGimbalSpeedCtrlR(0,0,0)==0;
        submitted_yaw=submitted_pitch=0; active=false;
        return accepted;
    };
    auto output=[&](bool ready,bool ok,const char *reason) {
        std::lock_guard<std::mutex> guard(feedback.mutex);
        const auto &s=feedback.state;
        std::cout << "{\"ok\":" << (ok?"true":"false") << ",\"ready\":" << (ready?"true":"false")
                  << ",\"error\":\"" << reason << "\",\"yaw_motor\":" << s.yaw_motor
                  << ",\"pitch_motor\":" << s.pitch_motor << ",\"reported_yaw_speed\":" << s.yaw_v
                  << ",\"reported_pitch_speed\":" << s.pitch_v << ",\"feedback_age_s\":" << age(feedback.at)
                  << ",\"feedback_valid\":" << (feedback.valid?"true":"false")
                  << ",\"submitted_yaw_speed\":" << submitted_yaw << ",\"submitted_pitch_speed\":" << submitted_pitch
                  << ",\"velocity_submitted\":true}" << std::endl;
    };
    const bool initial_stop=zero();
    output(true,initial_stop,initial_stop?"":"stop_delivery_uncertain");
    std::string buffer;
    bool failed=!initial_stop;
    while (!failed && !shutting_down && std::cout.good()) {
        bool fresh; double feedback_age;
        Device::AiGimbalStateInfo state{};
        {
            std::lock_guard<std::mutex> guard(feedback.mutex);
            feedback_age=age(feedback.at);
            fresh=feedback.valid && feedback_age<=.7;
            state=feedback.state;
        }
        if (active && (age(last_input)>.45 || !fresh) && !zero()) { failed=true; break; }
        pollfd input{STDIN_FILENO,POLLIN,0};
        int polled=poll(&input,1,40);
        if (polled<0) { if (shutting_down) break; zero(); failed=true; break; }
        if (!polled) continue;
        char bytes[256]; auto count=read(STDIN_FILENO,bytes,sizeof(bytes));
        if (count<=0) break;
        buffer.append(bytes,static_cast<size_t>(count));
        if (buffer.size()>512) { zero(); output(false,false,"invalid_command"); failed=true; break; }
        auto newline=buffer.find('\n');
        if (newline==std::string::npos) continue;
        // Host is single-flight: reject a backlog instead of replaying it.
        if (newline+1!=buffer.size()) { zero(); output(false,false,"command_backlog"); failed=true; break; }
        std::istringstream input_command(buffer.substr(0,newline)); buffer.clear();
        std::string verb,extra; double yaw=0,pitch=0;
        input_command>>verb;
        bool valid=verb=="get" || verb=="stop";
        if (verb=="speed") valid=bool(input_command>>yaw>>pitch) && std::isfinite(yaw) && std::isfinite(pitch)
                                    && std::abs(yaw)<=12 && std::abs(pitch)<=8;
        if ((input_command>>extra) || !valid) { zero(); output(false,false,"invalid_command"); failed=true; break; }
        if (verb!="get") last_input=Clock::now();
        if (verb=="stop" || (verb=="speed" && yaw==0 && pitch==0)) {
            if (!zero()) { output(false,false,"stop_delivery_uncertain"); failed=true; break; }
        } else if (verb=="speed") {
            if (shutting_down) { zero(); break; }
            if (!fresh) { zero(); output(false,false,"feedback_stale"); failed=true; break; }
            // Slow before fixed bounds using actual readback and feedback/watchdog
            // horizon. This never authorizes outward motion at a boundary.
            const double horizon=feedback_age+.45+.2;
            const double yaw_room=yaw>0?60-state.yaw_motor-.75:state.yaw_motor+35-.75;
            const double pitch_room=pitch>0?20-state.pitch_motor-.75:state.pitch_motor+20-.75;
            yaw=std::copysign(std::min(std::abs(yaw),std::max(0.,yaw_room/horizon)),yaw);
            pitch=std::copysign(std::min(std::abs(pitch),std::max(0.,pitch_room/horizon)),pitch);
            if (camera->aiSetGimbalSpeedCtrlR(pitch,-yaw,0)!=0) {
                zero(); output(false,false,"velocity_delivery_uncertain"); failed=true; break;
            }
            submitted_yaw=yaw; submitted_pitch=pitch; active=yaw!=0 || pitch!=0;
        }
        output(false,true,"");
    }
    zero(); running=false; reader.join();
    // Fence the queued safety zero before closing the SDK sender.
    Device::AiGimbalStateInfo final_state{};
    camera->aiGetGimbalStateR(&final_state);
    Devices::get().close();
    return failed?1:0;
}
