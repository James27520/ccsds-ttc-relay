#ifndef ADDA_DOPPLER_H
#define ADDA_DOPPLER_H
#include <stdint.h>

/* Build opt-in, separately from runtime mode. Existing firmware compiles out
 * the capture/controller hooks. No protocol or RF configuration is changed. */
#ifndef ADDA_DOPPLER_ENABLED
#define ADDA_DOPPLER_ENABLED 0
#endif

enum dp_mode { DP_OFF, DP_PREDICTION, DP_MEASUREMENT, DP_FUSION };
enum dp_state { DP_DISABLED, DP_PREDICT_ONLY, DP_MEASURE_ONLY, DP_HYBRID,
                DP_HOLD, DP_FAULT };
enum dp_result { DP_OK, DP_BAD_ARGUMENT, DP_EXPIRED, DP_QUALITY,
                 DP_WRONG_LINK, DP_ORDER, DP_OUTLIER };
struct dp_config {
    uint32_t link, channel;
    double alpha, beta, max_shift_hz, max_rate_hz_s;
    double max_residual_hz, max_residual_rate_hz_s, innovation_hz, min_quality;
    uint32_t fresh_ms, hold_ms, observation_max_age_ms;
};
/* All times use ONE local monotonic uint32 millisecond clock (wrap supported).
 * A segment describes physical RF CFO, not the sampled alias frequency.
 * Positive CFO raises received frequency; correction has the opposite sign.
 * No implicit UTC, orbit propagation, or cross-board clock conversion. */
struct dp_prediction {
    uint32_t start_ms, duration_ms;
    double rf_hz, cfo_hz, rate_hz_s;
};
struct dp_observation {
    uint32_t link, channel, capture_ms, sequence;
    double residual_hz, applied_correction_hz, quality;
    unsigned source_valid;
};
struct dp_output {
    enum dp_state state;
    double prediction_hz, residual_hz, total_hz, correction_hz, rate_hz_s;
    uint32_t measurement_age_ms;
    unsigned valid;
};
struct dp_tracker {
    struct dp_config config;
    struct dp_prediction prediction;
    enum dp_mode mode;
    unsigned model_valid, measured;
    uint32_t measurement_ms, sequence, accepted, rejected;
    double residual_hz, residual_rate_hz_s;
};
void dp_defaults(struct dp_config *, uint32_t link, uint32_t channel);
int dp_init(struct dp_tracker *, const struct dp_config *);
int dp_set_mode(struct dp_tracker *, enum dp_mode);
int dp_set_prediction(struct dp_tracker *, const struct dp_prediction *);
int dp_plan(const struct dp_tracker *, uint32_t at_ms, struct dp_output *);
int dp_observe(struct dp_tracker *, const struct dp_observation *, uint32_t now_ms);
/* Relative satellite-minus-ground vectors in ONE Cartesian inertial frame,
 * meters, m/s, m/s^2, evaluated at the same epoch. Positive radial speed means
 * receding. Returns received CFO and derivative, using one-way nonrelativistic
 * Doppler. The caller supplies ephemeris and the RF carrier, NOT desktop IF. */
int dp_geometry(double rf_hz, const double r[3], const double v[3],
                const double a[3], double *cfo_hz, double *rate_hz_s);
#endif
