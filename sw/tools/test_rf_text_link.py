"""Offline waveform/framing/carrier/timing rejection tests; no hardware access."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

import rf_text_link as link


def capture(iq, offset=-250_000, frequency_error=0, phase=0, inverted=False,
            start=0, n=8192, noise=8, seed=1):
    base = iq[:, 0].astype(float)+1j*iq[:, 1]
    signal = np.tile(base, (n+start)//len(base)+2)[start:start+n]
    t = (np.arange(n)+start)/link.FS
    signal *= np.exp(2j*np.pi*(offset-500_000+frequency_error)*t+1j*phase)
    signal *= (-1 if inverted else 1)*300/max(abs(base))
    rng = np.random.default_rng(seed)
    signal += noise*(rng.normal(size=n)+1j*rng.normal(size=n)) + 3-2j
    return np.rint(np.column_stack((signal.real, signal.imag))).astype("<i2").tobytes()


def custom_frame_iq(frame):
    bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8))
    n = len(bits)*25
    up = np.zeros(3*n); up[::25] = np.tile(1-2*bits.astype(float), 3)
    bb = np.convolve(up, link.srrc(.35,25,span=8), "same")[n:2*n]
    z = bb*np.exp(2j*np.pi*500_000*np.arange(n)/link.FS)
    return np.rint(np.column_stack((z.real,z.imag))*3000/max(abs(z))).astype("<i2")


class TextLinkTests(unittest.TestCase):
    def test_independent_crc_and_frame_known_values(self):
        self.assertEqual(link.crc16(b"123456789"), 0x29B1)
        self.assertEqual(link.build_frame("hello world").hex(),
                         "aaaa0b68656c6c6f20776f726c64efeb")

    def test_reference_frames_length_endian_and_periodic_shaping(self):
        for text in ("hello world", "relay test1", "relay test2"):
            iq, manifest = link.generate_iq(text)
            self.assertEqual(iq.shape, (3200,2))
            self.assertEqual(iq.dtype, np.dtype("<i2"))
            payload = text.encode()
            self.assertEqual(bytes.fromhex(manifest["frame_hex"]),
                             b"\xaa\xaa\x0b"+payload+struct.pack(">H",link.crc16(payload)))
            self.assertEqual(manifest["frame_bits"],128)
            bits = np.unpackbits(np.frombuffer(bytes.fromhex(manifest["frame_hex"]),dtype=np.uint8))
            up = np.zeros(4*3200);up[::25]=np.tile(1-2*bits.astype(float),4)
            bb = np.convolve(up,link.srrc(.35,25,span=8),"same")[3200:9600]
            z = bb*np.exp(2j*np.pi*500000*np.arange(len(bb))/link.FS)
            expected=np.rint(np.column_stack((z.real,z.imag))*.1*32767/max(abs(z))).astype("<i2")
            np.testing.assert_array_equal(np.tile(iq,(2,1)),expected)
            self.assertFalse(manifest["ccsds"])

    def test_unknown_phase_polarity_frequency_and_truncated_start(self):
        for k,(text,cfo,phase,start,invert) in enumerate([
            ("hello world",1234.5,1.13,417,False),
            ("relay test1",-1791.2,-2.1,1729,True),
            ("relay test2",6999.0,2.8,3107,False)]):
            with self.subTest(text=text):
                iq,_=link.generate_iq(text)
                result=link.decode(capture(iq,frequency_error=cfo,phase=phase,start=start,inverted=invert,seed=k))
                self.assertGreaterEqual(result["valid_frame_count"],1)
                self.assertLessEqual(result["valid_frame_count"],2)
                self.assertTrue(all(f["text"]==text for f in result["frames"]))
                self.assertLess(abs(result["carrier_offset_hz"]-(-250000+cfo)),30)
                self.assertIsNone(result["ber"])
                self.assertEqual(result["valid_frame_bits"],128*len(result["frames"]))
                for f in result["frames"]:
                    self.assertGreaterEqual(f["first_symbol_sample"],100)
                    self.assertLessEqual(f["sample_end_exclusive"],8192)
                starts=[f["first_symbol_sample"] for f in result["frames"]]
                self.assertEqual(len(set(starts)),len(starts))
                json.dumps(result,allow_nan=False)

    def test_positive_750k_branch_and_long_multi_frame_capture(self):
        iq,_=link.generate_iq("hello world")
        result=link.decode(capture(iq,offset=750000,frequency_error=-1300.2,phase=1.5,
                                   start=1433,n=16000),expected_offset_hz=750000)
        self.assertGreaterEqual(result["valid_frame_count"],4)
        self.assertLess(abs(result["carrier_offset_hz"]-748699.8),15)
        self.assertTrue(all(f["text"]=="hello world" for f in result["frames"]))

    def test_bad_crc_preserves_payload_and_is_rejected(self):
        good,gm=link.generate_iq("hello world")
        bad,bm=link.generate_iq("hello world",corrupt_crc=True)
        a,b=bytes.fromhex(gm["frame_hex"]),bytes.fromhex(bm["frame_hex"])
        self.assertEqual(a[:-1],b[:-1]);self.assertEqual(a[-1]^b[-1],1)
        self.assertTrue(bm["corrupt_crc"] and bm["test_only"])
        result=link.decode(capture(bad,phase=.7,start=811,noise=0))
        self.assertEqual(result["valid_frame_count"],0)
        self.assertGreater(result["crc_rejected_frames"],0)
        self.assertGreater(result["complete_evaluated_frames"],0)

    def test_bad_lengths_and_partial_candidates_rejected(self):
        for length in (0,201,255):
            frame=bytearray(link.build_frame("hello world"));frame[2]=length
            result=link.decode(capture(custom_frame_iq(frame),start=109,noise=0))
            self.assertEqual(result["valid_frame_count"],0)
        bits=np.unpackbits(np.frombuffer(b"\xaa\xaa\xc8hello",dtype=np.uint8))
        frames,stats=link._frames(bits,100,25,False)
        self.assertEqual(frames,[]);self.assertGreater(stats["incomplete_candidates"],0)

    def test_shifted_preamble_rejection_is_kept_and_identified(self):
        # Perfect decisions, no channel noise: the two leading bits produce a
        # false AAAA header at bit 0, and the real frame begins at bit 2.
        frame=link.build_frame("x"*33)
        bits=np.concatenate((np.array([1,0],dtype=np.uint8),
                             np.tile(np.unpackbits(np.frombuffer(frame,dtype=np.uint8)),4)))
        frames,stats=link._frames(bits,100,25,False)
        self.assertEqual(len(frames),4)
        self.assertTrue(all(f['text']=="x"*33 for f in frames))
        self.assertGreater(stats['crc_rejected_frames'],0)
        self.assertEqual(stats['overlapping_preamble_rejections'],1)
        self.assertEqual(stats['crc_rejected_candidates'][0],
                         dict(bit_offset=0,frame_bits=1128,overlaps_valid_preamble=True))

    def test_real_corrupt_frame_is_not_hidden_as_overlap(self):
        bad=link.build_frame('bad frame',corrupt_crc=True)
        good=link.build_frame('good frame')
        bits=np.unpackbits(np.frombuffer(bad+good,dtype=np.uint8))
        frames,stats=link._frames(bits,100,25,False)
        self.assertEqual([f['text'] for f in frames],['good frame'])
        self.assertEqual(stats['crc_rejected_frames'],1)
        self.assertEqual(stats['overlapping_preamble_rejections'],0)
        self.assertFalse(stats['crc_rejected_candidates'][0]['overlaps_valid_preamble'])

    def test_noise_tone_zero_never_become_text(self):
        rng=np.random.default_rng(17)
        cases=[np.zeros((8192,2),dtype="<i2"),np.rint(rng.normal(0,100,(8192,2))).astype("<i2")]
        z=200*np.exp(2j*np.pi*(-249110)*np.arange(8192)/link.FS)
        cases.append(np.rint(np.column_stack((z.real,z.imag))).astype("<i2"))
        for iq in cases:
            result=link.decode(iq.tobytes())
            self.assertEqual(result["valid_frame_count"],0)
            self.assertEqual(result["frames"],[])
            json.dumps(result,allow_nan=False)

    def test_utf8_byte_length_and_invalid_inputs(self):
        iq,m=link.generate_iq("测试")
        self.assertEqual(m["payload_bytes"],6)
        result=link.decode(capture(iq,start=1031))
        self.assertTrue(any(f["text"]=="测试" for f in result["frames"]))
        for text in ("", "x"*201):
            with self.assertRaises(ValueError):link.generate_iq(text)
        for args in ({"amplitude":0},{"amplitude":float("nan")},{"offset_hz":500001},
                     {"sample_rate_hz":2499999},{"corrupt_crc":1}):
            with self.assertRaises(ValueError):link.generate_iq("hello world",**args)
        for raw in (b"",b"abc",bytes(100*4),np.full((8192,2),2048,dtype="<i2").tobytes()):
            with self.assertRaises(ValueError):link.decode(raw)

    def test_cli_new_outputs_only(self):
        with tempfile.TemporaryDirectory() as directory,contextlib.redirect_stdout(io.StringIO()):
            out=Path(directory)/"wave"
            argv=["generate","--text","hello world","--out",str(out)]
            self.assertEqual(link.main(argv),0)
            before=(out/"iq_s16le.bin").read_bytes()
            with self.assertRaises(FileExistsError):link.main(argv)
            self.assertEqual((out/"iq_s16le.bin").read_bytes(),before)


if __name__=="__main__":
    unittest.main()
