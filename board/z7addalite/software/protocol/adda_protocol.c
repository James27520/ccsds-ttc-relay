#include "adda_protocol.h"
#include <limits.h>
#include <string.h>

static const uint8_t ap_asm[4] = {0x1a, 0xcf, 0xfc, 0x1d};

static int command_valid(const struct ap_command *command)
{
    if (!command) return AP_EARG;
    if (command->version != 1u && command->version != 0x21u &&
        command->version != 0x22u && command->version != 0x23u) return AP_EVERSION;
    if (command->rx_mhz < 70u || command->rx_mhz > 6000u ||
        command->tx_mhz < 70u || command->tx_mhz > 6000u) return AP_ERANGE;
    return AP_OK;
}

uint16_t ap_crc16(const uint8_t *data, size_t length)
{
    uint16_t crc = 0xffffu;
    size_t i;
    unsigned j;
    /* NULL with length 0 is the ordinary empty CRC. Callers must provide
     * valid storage for nonempty input; this primitive has no error channel. */
    for (i = 0; i < length; ++i) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (j = 0; j < 8u; ++j)
            crc = (uint16_t)((uint32_t)crc << 1 ^ ((crc & 0x8000u) ? 0x1021u : 0u));
    }
    return crc;
}

int ap_body_build(const struct ap_command *command, uint8_t body[AP_BODY_BYTES])
{
    uint16_t crc;
    int rc = command_valid(command);
    if (!body) return AP_EARG;
    if (rc != AP_OK) return rc;
    body[0] = command->version;
    body[1] = (uint8_t)command->rx_mhz;
    body[2] = (uint8_t)(command->rx_mhz >> 8);
    body[3] = (uint8_t)command->tx_mhz;
    body[4] = (uint8_t)(command->tx_mhz >> 8);
    body[5] = command->seq;
    crc = ap_crc16(body, 6u);
    body[6] = (uint8_t)(crc >> 8);
    body[7] = (uint8_t)crc;
    return AP_OK;
}

int ap_body_parse(const uint8_t *body, size_t length, struct ap_command *command)
{
    struct ap_command temporary;
    int rc;
    if (!body || !command) return AP_EARG;
    if (length != AP_BODY_BYTES) return AP_ELENGTH;
    if (ap_crc16(body, 6u) != (uint16_t)((uint16_t)body[6] << 8 | body[7])) return AP_ECRC;
    temporary.version = body[0];
    temporary.rx_mhz = (uint16_t)((uint16_t)body[2] << 8 | body[1]);
    temporary.tx_mhz = (uint16_t)((uint16_t)body[4] << 8 | body[3]);
    temporary.seq = body[5];
    rc = command_valid(&temporary);
    if (rc != AP_OK) return rc;
    *command = temporary;
    return AP_OK;
}

static int bits_valid(const uint8_t *bits, size_t length)
{
    size_t i;
    if (!bits) return AP_EARG;
    for (i = 0; i < length; ++i) if (bits[i] > 1u) return AP_EBIT;
    return AP_OK;
}

int ap_randomize_bits(const uint8_t *input, uint8_t *output, size_t length)
{
    uint8_t reg = 0xffu;
    size_t i;
    unsigned feedback;
    int rc;
    if (!output) return AP_EARG;
    rc = bits_valid(input, length);
    if (rc != AP_OK) return rc;
    for (i = 0; i < length; ++i) {
        feedback = ((unsigned)reg ^ (reg >> 2) ^ (reg >> 4) ^ (reg >> 7)) & 1u;
        output[i] = (uint8_t)(input[i] ^ (reg >> 7));
        reg = (uint8_t)((unsigned)reg << 1 | feedback);
    }
    return AP_OK;
}

static unsigned parity(unsigned word)
{
    word ^= word >> 4;
    word ^= word >> 2;
    word ^= word >> 1;
    return word & 1u;
}

int ap_conv_encode64(const uint8_t input[AP_DATA_BITS], uint8_t output[AP_CODE_BITS])
{
    unsigned reg = 0u;
    size_t i;
    int rc;
    if (!output) return AP_EARG;
    rc = bits_valid(input, AP_DATA_BITS);
    if (rc != AP_OK) return rc;
    for (i = 0; i < AP_DATA_BITS; ++i) {
        reg = ((reg << 1) | input[i]) & 0x7fu;
        output[2u*i] = (uint8_t)parity(reg & 0x79u);
        output[2u*i+1u] = (uint8_t)(parity(reg & 0x5bu) ^ 1u);
    }
    return AP_OK;
}

int ap_viterbi64(const uint8_t input[AP_CODE_BITS], uint8_t output[AP_DATA_BITS],
                 unsigned *metric, unsigned *end_state)
{
    uint16_t previous[64], current[64];
    uint8_t survivor[64][64];
    unsigned st, t, k, word, predecessor, cost, best_cost, best_predecessor, last;
    int rc;
    if (!output) return AP_EARG;
    rc = bits_valid(input, AP_CODE_BITS);
    if (rc != AP_OK) return rc;
    for (st = 0; st < 64u; ++st) previous[st] = 0x3fffu;
    previous[0] = 0u;
    for (t = 0; t < 64u; ++t) {
        for (st = 0; st < 64u; ++st) {
            best_cost = UINT_MAX;
            best_predecessor = 0u;
            for (k = 0; k < 2u; ++k) {
                predecessor = (st >> 1) | (k << 5);
                word = (predecessor << 1) | (st & 1u);
                cost = previous[predecessor] +
                    (unsigned)(parity(word & 0x79u) != input[2u*t]) +
                    (unsigned)((parity(word & 0x5bu) ^ 1u) != input[2u*t+1u]);
                if (cost < best_cost) { best_cost = cost; best_predecessor = predecessor; }
            }
            current[st] = (uint16_t)best_cost;
            survivor[t][st] = (uint8_t)best_predecessor;
        }
        memcpy(previous, current, sizeof(previous));
    }
    last = 0u;
    for (st = 1; st < 64u; ++st) if (previous[st] < previous[last]) last = st;
    if (metric) *metric = previous[last];
    if (end_state) *end_state = last;
    st = last;
    for (t = 64u; t > 0u; --t) {
        output[t-1u] = (uint8_t)(st & 1u);
        st = survivor[t-1u][st];
    }
    return AP_OK;
}

static void bytes_to_bits(const uint8_t *input, size_t bytes, uint8_t *output)
{
    size_t i;
    unsigned b;
    for (i = 0; i < bytes; ++i)
        for (b = 0; b < 8u; ++b) output[i*8u+b] = (uint8_t)(((unsigned)input[i] >> (7u-b)) & 1u);
}

static void bits_to_bytes(const uint8_t *input, size_t bytes, uint8_t *output)
{
    size_t i;
    unsigned b;
    for (i = 0; i < bytes; ++i) {
        output[i] = 0u;
        for (b = 0; b < 8u; ++b) output[i] = (uint8_t)((output[i] << 1) | input[i*8u+b]);
    }
}

int ap_frame_encode(const struct ap_command *command, uint8_t output[AP_FRAME_BITS])
{
    uint8_t body[AP_BODY_BYTES], bits[AP_DATA_BITS];
    int rc;
    if (!output) return AP_EARG;
    rc = ap_body_build(command, body);
    if (rc != AP_OK) return rc;
    bytes_to_bits(body, sizeof(body), bits);
    (void)ap_randomize_bits(bits, bits, sizeof(bits));
    bytes_to_bits(ap_asm, sizeof(ap_asm), output);
    return ap_conv_encode64(bits, output+32u);
}

int ap_find_frame(const uint8_t *bits, size_t bit_count, size_t start_bit,
                   struct ap_frame_result *result)
{
    struct ap_frame_result temporary;
    uint8_t coded[AP_CODE_BITS], decoded[AP_DATA_BITS];
    size_t offset;
    unsigned errors, inverted, j;
    int rc, candidate_error = AP_ENOFRAME;
    if (!result || !bits || start_bit > bit_count) return AP_EARG;
    rc = bits_valid(bits, bit_count);
    if (rc != AP_OK) return rc;
    if (bit_count-start_bit < 32u) return AP_ETRUNCATED;
    for (offset = start_bit; offset <= bit_count-32u; ++offset) {
        errors = 0u;
        for (j = 0; j < 32u; ++j)
            errors += (unsigned)(bits[offset+j] != (((unsigned)ap_asm[j/8u] >> (7u-j%8u)) & 1u));
        if (errors <= 2u) inverted = 0u;
        else if (errors >= 30u) { inverted = 1u; errors = 32u-errors; }
        else continue;
        if (bit_count-offset < AP_FRAME_BITS) {
            if (candidate_error == AP_ENOFRAME) candidate_error = AP_ETRUNCATED;
            continue;
        }
        for (j = 0; j < AP_CODE_BITS; ++j) coded[j] = (uint8_t)(bits[offset+32u+j] ^ inverted);
        (void)ap_viterbi64(coded, decoded, &temporary.path_metric, &temporary.end_state);
        (void)ap_randomize_bits(decoded, decoded, sizeof(decoded));
        bits_to_bytes(decoded, AP_BODY_BYTES, temporary.body);
        rc = ap_body_parse(temporary.body, sizeof(temporary.body), &temporary.command);
        if (rc != AP_OK) {
            if (candidate_error == AP_ENOFRAME || candidate_error == AP_ETRUNCATED) candidate_error = rc;
            continue;
        }
        temporary.bit_offset = offset;
        temporary.asm_errors = errors;
        temporary.inverted = inverted;
        *result = temporary;
        return AP_OK;
    }
    return candidate_error;
}

static void put_be64(uint8_t *output, uint64_t value)
{
    unsigned i;
    for (i = 0; i < 8u; ++i) output[i] = (uint8_t)(value >> (56u-8u*i));
}

int ap_rf_packet(const struct ap_command *command, uint16_t transaction_seq,
                   uint8_t rx_gain_db, uint8_t tx_att_db, uint8_t output[AP_RF_BYTES])
{
    uint8_t temporary[AP_RF_BYTES];
    uint16_t crc;
    int rc = command_valid(command);
    if (!output) return AP_EARG;
    if (rc != AP_OK) return rc;
    if (command->version != 1u) return AP_EVERSION;
    if (transaction_seq > 0x3fffu || rx_gain_db > 76u || tx_att_db > 89u) return AP_ERANGE;
    temporary[0] = 0x01u; temporary[1] = 0x01u;
    temporary[2] = (uint8_t)(0xc0u | (transaction_seq >> 8));
    temporary[3] = (uint8_t)transaction_seq;
    temporary[4] = 0u; temporary[5] = 17u;
    put_be64(temporary+6u, (uint64_t)command->rx_mhz * UINT64_C(1000000));
    put_be64(temporary+14u, (uint64_t)command->tx_mhz * UINT64_C(1000000));
    temporary[22] = rx_gain_db; temporary[23] = tx_att_db;
    crc = ap_crc16(temporary, 24u);
    temporary[24] = (uint8_t)(crc >> 8); temporary[25] = (uint8_t)crc;
    memcpy(output, temporary, sizeof(temporary));
    return AP_OK;
}

static uint32_t get32(const uint8_t *p)
{ return (uint32_t)p[0]<<24 | (uint32_t)p[1]<<16 | (uint32_t)p[2]<<8 | p[3]; }
static uint64_t get64(const uint8_t *p) { return (uint64_t)get32(p)<<32 | get32(p+4); }
int ap_control_packet(const struct ap_command *c,uint16_t seq,uint8_t *out,size_t capacity)
{
    uint8_t p[AP_CONTROL_BYTES];uint16_t crc;int rc=command_valid(c);
    if(!out)return AP_EARG;
    if(rc!=AP_OK)return rc;
    if(c->version==1u)return AP_EVERSION;
    if(seq>0x3fffu)return AP_ERANGE;
    if(capacity<sizeof(p))return AP_ELENGTH;
    memset(p,0,sizeof(p));p[0]=1;p[1]=0x20;p[2]=(uint8_t)(0xc0u|(seq>>8));p[3]=(uint8_t)seq;
    p[5]=27;p[6]=1;p[7]=c->version;
    if(c->version==0x21u){p[8]=1;p[9]=30;p[10]=50;p[13]=4;p[14]=0x93;p[15]=0xe0;}
    put_be64(p+16,(uint64_t)c->rx_mhz*UINT64_C(1000000));
    put_be64(p+24,(uint64_t)c->tx_mhz*UINT64_C(1000000));
    crc=ap_crc16(p,32);p[32]=(uint8_t)(crc>>8);p[33]=(uint8_t)crc;
    memcpy(out,p,sizeof(p));return AP_OK;
}
int ap_control_ack_parse(const uint8_t *p,size_t length,struct ap_ack *ack,struct ap_relay_status *status)
{
    struct ap_ack a;struct ap_relay_status s;
    if(!p || !ack || !status)return AP_EARG;
    if(length!=AP_CONTROL_ACK_BYTES)return AP_ELENGTH;
    if(ap_crc16(p,48)!=(uint16_t)((uint16_t)p[48]<<8|p[49]))return AP_ECRC;
    if(p[0]!=2 || p[1]!=0x20 || (p[2]&0xc0u)!=0xc0u || p[4] || p[5]!=43 || p[6]!=1 ||
       p[7]<0x21 || p[7]>0x23 || (p[8]&0xf0u) || p[9]>3)return AP_EACK;
    a.seq=(uint16_t)(((p[2]&0x3fu)<<8)|p[3]);a.rx_hz=get64(p+28);a.tx_hz=get64(p+36);
    {uint32_t rc=get32(p+44);a.rc=rc<=INT32_MAX?(int32_t)rc:(int32_t)(-1-(int64_t)(UINT32_MAX-rc));}
    s.operation=p[7];s.flags=p[8];s.mode=p[9];s.rx1_gain=p[10];s.rx2_gain=p[11];
    s.tx1_mdB=get32(p+12);s.tx2_mdB=get32(p+16);s.remaining_ms=get32(p+20);s.uptime_ms=get32(p+24);
    if((s.flags&1u) && (s.rx1_gain>76 || s.rx2_gain>76 || s.tx1_mdB>89000 || s.tx2_mdB>89000))return AP_EACK;
    *ack=a;*status=s;return AP_OK;
}

struct parser { const uint8_t *text; size_t length; size_t position; };

static int literal(struct parser *p, const char *expected)
{
    while (*expected) {
        if (p->position >= p->length || p->text[p->position] != (uint8_t)*expected) return 0;
        ++p->position; ++expected;
    }
    return 1;
}

static int decimal(struct parser *p, uint64_t maximum, uint64_t *value)
{
    uint64_t number = 0u;
    size_t begin = p->position;
    unsigned digit;
    while (p->position < p->length && p->text[p->position] >= '0' && p->text[p->position] <= '9') {
        digit = (unsigned)(p->text[p->position]-'0');
        if (number > maximum/10u || (number == maximum/10u && digit > maximum%10u)) return 0;
        number = number*10u+digit;
        ++p->position;
    }
    if (p->position == begin) return 0;
    *value = number;
    return 1;
}

int ap_ack_parse(const uint8_t *text, size_t length, struct ap_ack *ack)
{
    struct parser p;
    struct ap_ack temporary;
    uint64_t value;
    unsigned negative = 0u;
    if (!text || !ack) return AP_EARG;
    if (length == 0u || length >= AP_ACK_MAX_BYTES) return AP_ELENGTH;
    p.text = text; p.length = length; p.position = 0u;
    if (!literal(&p, "rc=")) return AP_EACK;
    if (p.position < p.length && p.text[p.position] == '-') { negative = 1u; ++p.position; }
    if (!decimal(&p, negative ? UINT64_C(2147483648) : UINT64_C(2147483647), &value)) return AP_EACK;
    temporary.rc = negative ? (int32_t)(-(int64_t)value) : (int32_t)value;
    if (!literal(&p, " seq=") || !decimal(&p, 0x3fffu, &value)) return AP_EACK;
    temporary.seq = (uint16_t)value;
    if (!literal(&p, " rx_hz=") || !decimal(&p, UINT64_MAX, &temporary.rx_hz)) return AP_EACK;
    if (!literal(&p, " tx_hz=") || !decimal(&p, UINT64_MAX, &temporary.tx_hz)) return AP_EACK;
    if (p.position < p.length && p.text[p.position] == '\r') ++p.position;
    if (!literal(&p, "\n") || p.position != p.length) return AP_EACK;
    *ack = temporary;
    return AP_OK;
}

static int same_command(const struct ap_command *a, const struct ap_command *b)
{
    return a->version == b->version && a->rx_mhz == b->rx_mhz &&
           a->tx_mhz == b->tx_mhz && a->seq == b->seq;
}

void ap_transaction_init(struct ap_transaction *state, uint16_t first_transaction_seq)
{
    if (!state) return;
    memset(state, 0, sizeof(*state));
    state->next_transaction_seq = first_transaction_seq;
}

int ap_transaction_begin(struct ap_transaction *state, const struct ap_command *command,
                           uint8_t rx_gain_db, uint8_t tx_att_db)
{
    uint8_t packet[AP_CONTROL_BYTES];size_t length;
    int rc;
    if (!state || !command) return AP_EARG;
    length=command->version==1u?AP_RF_BYTES:AP_CONTROL_BYTES;
    rc = command->version==1u?ap_rf_packet(command, state->next_transaction_seq, rx_gain_db, tx_att_db, packet):
         ap_control_packet(command,state->next_transaction_seq,packet,sizeof(packet));
    if (state->applied_valid && command->seq == state->applied_command.seq) {
        if (same_command(command, &state->applied_command) && rx_gain_db == state->applied_gain &&
            tx_att_db == state->applied_attenuation) return AP_DUPLICATE;
        return AP_ECONFLICT;
    }
    if (state->pending) {
        if (command->seq != state->pending_command.seq) return AP_EBUSY;
        if (same_command(command, &state->pending_command) && rx_gain_db == state->pending_gain &&
            tx_att_db == state->pending_attenuation) return AP_PENDING;
        return AP_ECONFLICT;
    }
    if (rc != AP_OK) return rc;
    memcpy(state->packet, packet, length);state->packet_length=length;
    state->pending_transaction_seq = state->next_transaction_seq;
    if(command->version!=1u)state->control_sequence_used=1u;
    state->next_transaction_seq = (uint16_t)(state->next_transaction_seq+1u);
    if(!state->control_sequence_used)state->next_transaction_seq &= 0x3fffu;
    state->pending_command = *command;
    state->pending_gain = rx_gain_db;
    state->pending_attenuation = tx_att_db;
    state->pending = 1u;
    return AP_OK;
}

static uint64_t distance(uint64_t a, uint64_t b) { return a > b ? a-b : b-a; }

int ap_transaction_ack(struct ap_transaction *state, const struct ap_ack *ack,
                        uint32_t tolerance_hz)
{
    if (!state || !ack) return AP_EARG;
    if (tolerance_hz > 10000u) return AP_ERANGE;
    if (!state->pending || ack->seq != state->pending_transaction_seq) return AP_ESTALE;
    if(state->pending_command.version!=1u)return AP_EACK;
    if (ack->rc != 0) return AP_EREMOTE;
    if (distance(ack->rx_hz, (uint64_t)state->pending_command.rx_mhz*UINT64_C(1000000)) > tolerance_hz ||
        distance(ack->tx_hz, (uint64_t)state->pending_command.tx_mhz*UINT64_C(1000000)) > tolerance_hz)
        return AP_EMISMATCH;
    state->applied_command = state->pending_command;
    state->applied_gain = state->pending_gain;
    state->applied_attenuation = state->pending_attenuation;
    state->applied_valid = 1u;
    state->pending = 0u;
    return AP_OK;
}

int ap_transaction_control_ack(struct ap_transaction *s,const struct ap_ack *a,const struct ap_relay_status *r,uint32_t tolerance)
{
    if(!s || !a || !r)return AP_EARG;
    if(tolerance>10000u)return AP_ERANGE;
    if(!s->pending || a->seq!=s->pending_transaction_seq)return AP_ESTALE;
    if(s->pending_command.version==1u || r->operation!=s->pending_command.version)return AP_EACK;
    if(a->rc)return AP_EREMOTE;
    if(!(r->flags&1u))return AP_EMISMATCH;
    if(r->operation==0x21u &&
       (distance(a->rx_hz,(uint64_t)s->pending_command.rx_mhz*UINT64_C(1000000))>tolerance ||
        distance(a->tx_hz,(uint64_t)s->pending_command.tx_mhz*UINT64_C(1000000))>tolerance ||
        r->mode!=1u || r->rx1_gain!=30 || r->rx2_gain!=30 || r->tx1_mdB!=50000 || r->tx2_mdB!=50000 ||
        !(r->flags&2u) || (r->flags&8u) || !r->remaining_ms || r->remaining_ms>get32(s->packet+12)))return AP_EMISMATCH;
    if(r->operation==0x22u && (r->mode!=2u || r->rx1_gain || r->rx2_gain ||
       r->tx1_mdB!=89000 || r->tx2_mdB!=89000 || (r->flags&2u) || r->remaining_ms))return AP_EMISMATCH;
    s->applied_command=s->pending_command;s->applied_gain=s->pending_gain;
    s->applied_attenuation=s->pending_attenuation;s->applied_valid=1;s->pending=0;return AP_OK;
}

void ap_transaction_abort(struct ap_transaction *state)
{
    if (state) state->pending = 0u;
}
