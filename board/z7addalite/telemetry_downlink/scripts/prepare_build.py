"""Create a separate, hash-recorded TM candidate from the frozen r4c inputs.

Never changes the frozen project or opens hardware. Run Vivado only on the
resulting ASCII directory. Derived sources are recorded for review/rebuild.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parents[1]
BASE = HERE.parent / "telecontrol_system"


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Frozen source anchor changed: {old[:90]!r}")
    return text.replace(old, new, 1)


def prepare(out):
    out = out.resolve()
    if not str(out).isascii() or out.exists():
        raise ValueError("Use a new ASCII output directory")
    manifest = json.loads((BASE / "SOURCE_MANIFEST.json").read_text(encoding="utf-8-sig"))
    for entry in manifest["files"]:
        path = BASE / entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Frozen input mismatch: {path}")
    out.mkdir(parents=True)
    for directory in ("src", "constraints", "abi", "scripts", "vendor", "reference", "sim"):
        shutil.copytree(BASE / directory, out / directory)
    for directory in ("reports", "artifacts"):
        (out / directory).mkdir()
    for source in (HERE / "src").glob("*.v"):
        shutil.copy2(source, out / "src" / source.name)
    for source in (HERE / "sim").glob("*.sv"):
        shutil.copy2(source, out / "sim" / source.name)
    for name in ("run_packet_sim.ps1", "run_dac_config_sim.ps1", "run_dac_io_sim.ps1"):
        shutil.copy2(HERE / "scripts" / name, out / "scripts" / name)
    top_path = out / "src/telecontrol_top.v"
    top = top_path.read_text()
    top = replace_once(top, "output dac_sda,", "inout dac_sda,")
    start = top.index(" assign dac_rstn=0;")
    end = top.index(" wire mode_start", start)
    top = top[:start] + top[end:]
    top = replace_once(top, ".clkdiv(clk_vec),.delay_ready", ".clkdiv(clk_vec),.dco_raw(tm_dco),.delay_ready")
    top = replace_once(top, " wire clk_vec,delay_ready;", " wire tm_dco;\n wire clk_vec,delay_ready;")
    top = replace_once(top, " wire memory_write;", """
 wire tm_wr_select=ctrl_wr_addr[31:12]==20'h43c01;
 wire tm_rd_select=ctrl_rd_addr[31:12]==20'h43c01;
 wire capture_wr_error,capture_rd_error,tm_wr_error,tm_rd_error;
 wire [31:0] capture_rd_data,tm_rd_data;
 assign ctrl_wr_error=tm_wr_select?tm_wr_error:capture_wr_error;
 assign ctrl_rd_error=tm_rd_select?tm_rd_error:capture_rd_error;
 assign ctrl_rd_data=tm_rd_select?tm_rd_data:capture_rd_data;
 wire tm_clk,tm_locked;
 clk_wiz_tm tm_clock(.clk_in1(tm_dco),.reset(reset25 || !startup_finished),.clk_out1(tm_clk),.locked(tm_locked));
 wire tm_reset_async=reset_async || ps_reset_sync[2] || !tm_locked;
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] tm_ctrl_reset_sync=7,tm_dac_reset_sync=7;
 always @(posedge clk25 or posedge tm_reset_async)if(tm_reset_async)tm_ctrl_reset_sync<=7;else tm_ctrl_reset_sync<={tm_ctrl_reset_sync[1:0],1'b0};
 always @(posedge tm_clk or posedge tm_reset_async)if(tm_reset_async)tm_dac_reset_sync<=7;else tm_dac_reset_sync<={tm_dac_reset_sync[1:0],1'b0};
 wire tm_reset25=tm_ctrl_reset_sync[2],tm_reset_dac=tm_dac_reset_sync[2];
 wire tm_config_verified,tm_config_finished,tm_sdo,tm_oe;
 wire [31:0] tm_config_diagnostic;
 assign dac_rstn=!tm_reset25 && !tm_reset_async;
 assign dac_sda=tm_oe?tm_sdo:1'bz;
 tm_dac_config tm_configuration(.clk25(clk25),.reset(tm_reset25),.start_allowed(startup_finished),
 .sdi(dac_sda),.sdo(tm_sdo),.sdo_enable(tm_oe),.cs_n(dac_cs),.sclk(dac_sclk),
 .verified(tm_config_verified),.finished(tm_config_finished),.diagnostic(tm_config_diagnostic));
 (* ASYNC_REG="TRUE",SHREG_EXTRACT="NO" *) reg [2:0] tm_config_sync=0;
 always @(posedge tm_clk or posedge tm_reset_async)if(tm_reset_async)tm_config_sync<=0;else tm_config_sync<={tm_config_sync[1:0],tm_config_verified};
 wire signed [15:0] tm_sample;
 wire [31:0] tm_engine_rd_data;wire tm_engine_rd_error;
 assign tm_rd_data=(ctrl_rd_addr==32'h43c01030)?tm_config_diagnostic:
                   (ctrl_rd_addr==32'h43c01034)?{30'd0,tm_config_finished,tm_config_verified}:tm_engine_rd_data;
 assign tm_rd_error=(ctrl_rd_addr==32'h43c01030 || ctrl_rd_addr==32'h43c01034)?1'b0:tm_engine_rd_error;
 tm_packet_tx tm_transmitter(.clk25(clk25),.reset25(tm_reset25),.dac_clk(tm_clk),.dac_reset(tm_reset_dac),
 .config_verified(tm_config_sync[2]),.wr_en(ctrl_wr_en && tm_wr_select),.wr_addr(ctrl_wr_addr),
 .wr_data(ctrl_wr_data),.wr_strb(ctrl_wr_strb),.wr_error(tm_wr_error),.rd_addr(ctrl_rd_addr),
 .rd_data(tm_engine_rd_data),.rd_error(tm_engine_rd_error),.dac_sample(tm_sample),.tx_active(),.tx_bit(),.tx_symbol_start());
 tm_dac_io tm_output(.dac_clk(tm_clk),.reset(tm_reset_dac || tm_reset_async),.sample(tm_sample),
 .dci_p(dac_dci_p),.dci_n(dac_dci_n),.frame_p(dac_frame_p),.frame_n(dac_frame_n),.data_p(dac_data_p),.data_n(dac_data_n));
 wire memory_write;""")
    old = ".wr_en(ctrl_wr_en),.wr_addr(ctrl_wr_addr),.wr_data(ctrl_wr_data),.wr_strb(ctrl_wr_strb),.wr_error(ctrl_wr_error),.rd_addr(ctrl_rd_addr),.rd_data(ctrl_rd_data),.rd_error(ctrl_rd_error),"
    new = ".wr_en(ctrl_wr_en && !tm_wr_select),.wr_addr(ctrl_wr_addr),.wr_data(ctrl_wr_data),.wr_strb(ctrl_wr_strb),.wr_error(capture_wr_error),.rd_addr(ctrl_rd_addr),.rd_data(capture_rd_data),.rd_error(capture_rd_error),"
    top = replace_once(top, old, new)
    top_path.write_text(top)
    adc_path = out / "src/adc_rx8.v"
    adc = replace_once(adc_path.read_text(), "output clkdiv,output delay_ready", "output dco_raw,output clkdiv,output delay_ready")
    adc = replace_once(adc, " wire dco,clkio;", " wire dco,clkio;\n assign dco_raw=dco;")
    adc_path.write_text(adc)
    build_path = out / "scripts/build.tcl"
    build = build_path.read_text()
    build = replace_once(build, "generate_target all [get_ips {clk_wiz_tc ila_tc}]", """create_ip -name clk_wiz -vendor xilinx.com -library ip -version 6.0 -module_name clk_wiz_tm
set_property -dict [list CONFIG.PRIM_IN_FREQ {125.000} CONFIG.PRIM_SOURCE {No_buffer} CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {250.000} CONFIG.USE_LOCKED {true} CONFIG.RESET_TYPE {ACTIVE_HIGH} CONFIG.RESET_PORT {reset}] [get_ips clk_wiz_tm]
add_files -fileset constrs_1 [file join $root constraints telemetry.xdc]
generate_target all [get_ips {clk_wiz_tc clk_wiz_tm ila_tc}]""")
    build = replace_once(build, "!= 8}", "!= 12}")
    build = replace_once(build, "Expected four mailbox toggle/ack first stage pairs", "Expected six mailbox toggle/ack first stage pairs")
    build_path.write_text(build)
    shutil.copy2(HERE / "constraints/telemetry.xdc", out / "constraints/telemetry.xdc")
    signoff = out / "scripts/signoff.tcl"
    signoff.write_text(signoff.read_text()+"\nsource [file join $root scripts tm_signoff.tcl]\n")
    shutil.copy2(HERE / "scripts/tm_signoff.tcl", out / "scripts/tm_signoff.tcl")
    export_path = out / "scripts/export_reviewed.tcl"
    export = replace_once(export_path.read_text(), "open_project [file join $root build telecontrol_system.xpr]", """set f [open [file join $root reports tm_signoff.txt] r];set tm_signoff [read $f];close $f
if {![regexp {TM_STA_PASS=1\\s} $tm_signoff]} {error "Missing successful routed DAC signoff"}
open_project [file join $root build telecontrol_system.xpr]""")
    export = replace_once(export, "set run_bit [file join", "source [file join $root scripts tm_signoff.tcl]\nset run_bit [file join")
    export_path.write_text(export)
    files = []
    for directory in ("src", "constraints", "abi", "scripts", "vendor", "sim", "reference"):
        for path in sorted((out / directory).rglob("*")):
            if path.is_file():
                files.append({"path": path.relative_to(out).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
    overlay = {p.relative_to(HERE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(HERE.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}
    (out / "SOURCE_MANIFEST.json").write_text(json.dumps({"part":"xc7z020clg484-2", "source_revision":"tm1-candidate", "base_revision":"r4c", "base_manifest_sha256":hashlib.sha256((BASE/"SOURCE_MANIFEST.json").read_bytes()).hexdigest(), "overlay_sources":overlay, "files":files}, indent=2)+"\n")
    print(out)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    prepare(parser.parse_args().out)
