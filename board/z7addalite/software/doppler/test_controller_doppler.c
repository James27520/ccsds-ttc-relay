/* Reuse the existing full register/UDP mock and regressions, then exercise
 * the opt-in hook through the real controller decode entry, not a fake CFO. */
#define main capture_regressions
#include "../../ps_software/test_capture_controller.c"
#undef main
int main(void)
{
    unsigned n,w;capture_regressions();
    setup();CHECK(ctrl.doppler.mode==DP_OFF);
    n=model.sends;w=model.writes;
    CHECK(act_command_line(&ctrl,"doppler hybrid")==AP_EARG);
    CHECK(act_command_line(&ctrl,"doppler radial -6000 10 10000")==AP_OK);
    CHECK(ctrl.doppler.mode==DP_OFF && ctrl.doppler.prediction.cfo_hz>2000 &&
          ctrl.doppler.prediction.rate_hz_s<0);
    CHECK(act_command_line(&ctrl,"doppler model nan 0 10000")==AP_EARG);
    CHECK(act_command_line(&ctrl,"doppler model 0 0 10000 junk")==AP_EARG);
    CHECK(act_command_line(&ctrl,"doppler model 16700 0 10000")==AP_OK);
    CHECK(ctrl.doppler.mode==DP_OFF);
    CHECK(act_command_line(&ctrl,"doppler hybrid")==AP_OK);
    CHECK(model.sends==n && model.writes==w && !core.armed && !ctrl.automatic);
    model.synthetic_words=1;arm(TC_MODE_NORMAL);finish_capture(&model);drain();
    CHECK(cap.arm_ms<=cap.done_ms && cap.done_ms<model.ms);
    aps_set_network_ready(&core,1);core.armed=1;
    CHECK(act_command_line(&ctrl,"decode")==AP_OK);
    CHECK(ctrl.doppler_trace.planned && ctrl.doppler_trace.crc_ok);
    CHECK(ctrl.doppler.accepted==1 && ctrl.doppler_trace.observation_result==DP_OK);
    CHECK(ctrl.doppler.measurement_ms==cap.arm_ms);
    CHECK(core.decoded_frames==1 && model.sends==1 && core.transaction.pending);
    CHECK(act_command_line(&ctrl,"decode")==AP_EBUSY || ctrl.consumed);
    CHECK(ctrl.doppler.accepted==1);
    CHECK(act_command_line(&ctrl,"doppler off")==AP_OK && ctrl.doppler.mode==DP_OFF);
    /* Opt-in commands never alter the separate forwarding authorization. */
    CHECK(core.armed && model.sends==1);
    setup();model.synthetic_words=1;
    CHECK(act_command_line(&ctrl,"doppler model 0 0 10000")==AP_OK);
    CHECK(act_command_line(&ctrl,"doppler hybrid")==AP_OK);
    arm(TC_MODE_TRAINING);finish_capture(&model);drain();
    aps_set_network_ready(&core,1);core.armed=1;
    CHECK(act_command_line(&ctrl,"decode")==AP_OK);
    CHECK(!ctrl.doppler.accepted && !ctrl.doppler_trace.planned && !model.sends);
    puts("PASS opt-in controller: real demod over mock ADC; no board I/O");return 0;
}
