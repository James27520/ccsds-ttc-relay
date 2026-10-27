#ifndef ADDA_CONTROLLER_H
#define ADDA_CONTROLLER_H
#include "adda_ps_core.h"
#include "adda_capture.h"
struct act_clock {void *context; uint32_t (*now_ms)(void *);};
struct act_controller {
    struct aps_state *core;
    struct ac_capture *capture;
    struct act_clock clock;
    unsigned automatic, consumed;
    enum ac_state reported_state;
};
void act_init(struct act_controller *,struct aps_state *,struct ac_capture *,const struct act_clock *);
/* Platform polls Ethernet/UART/timers before this cooperative iteration.
 * ADC BRAM copying is sliced; decoding is synchronous and never starts while
 * an ACK transaction is pending. Timing for UDP is taken AFTER decoding. */
void act_poll(struct act_controller *);
int act_command_line(struct act_controller *,const char *line);
int act_waveformtest(struct act_controller *);
#endif
