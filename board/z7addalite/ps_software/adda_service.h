#ifndef ADDA_SERVICE_H
#define ADDA_SERVICE_H
#include "adda_controller.h"
#include "adda_telemetry_tx.h"
#define ASV_LEASE_MS 600000u
#define ASV_TRANSACTION_LIMIT 16u
#define ASV_REPLY_DELAY_MS 3000u
#define ASV_REPLY_PERIOD_MS 50u
#define ASV_REPLY_LIMIT 400u
#define ASV_REPLY_WINDOW_MS (ASV_REPLY_PERIOD_MS*ASV_REPLY_LIMIT)
enum asv_state { ASV_OFF=0,ASV_LISTEN=1,ASV_WAIT_ACK=2,ASV_DELAY=3,ASV_REPLY=4,ASV_STOPPING=5 };
enum asv_reason { ASV_NONE=0,ASV_USER=1,ASV_LEASE=2,ASV_LIMIT=3,ASV_NETWORK=4,
                  ASV_CAPTURE=5,ASV_DECODE=6,ASV_UDP=7,ASV_TM=8 };
struct asv_service {
    struct act_controller *controller;
    struct atm_tx *tx;
    unsigned active,state,reason,accepted,completed,failed,reply_sent,used_count;
    uint32_t started_ms,ack_ms,last_reply_ms,reply_seq,baseline_applied,baseline_failures;
    uint8_t used[32],burst[ATM_BURST_BYTES];
    struct ap_command command;
    uint16_t udp_seq;
};
void asv_init(struct asv_service *,struct act_controller *,struct atm_tx *);
int asv_start(struct asv_service *,uint32_t now);
int asv_stop(struct asv_service *,enum asv_reason,uint32_t now);
/* Main must poll network and atm_tx_poll before this fast cooperative step,
 * and call act_poll afterwards. Service filter pauses auto before UDP begins. */
void asv_poll(struct asv_service *,uint32_t now);
/* Complete decimal status, one line, <=15 fields; no hardware writes. */
int asv_status(const struct asv_service *,uint32_t now,char *,size_t);
/* 1 if the command must cancel an active service; read-only commands remain
 * allowed, all other writes are rejected while active or STOP is draining. */
int asv_cancel_command(const char *);
int asv_command_allowed(const struct asv_service *,const char *);
#endif
