# Definitional proc to organize widgets for parameters.
proc init_gui { IPINST } {
  ipgui::add_param $IPINST -name "Component_Name"
  #Adding Page
  set Page_0 [ipgui::add_page $IPINST -name "Page 0"]
  ipgui::add_param $IPINST -name "PHY_MODE_1R1T" -parent ${Page_0}
  ipgui::add_param $IPINST -name "PHY_MODE_2R2T" -parent ${Page_0}


}

proc update_PARAM_VALUE.PHY_MODE_1R1T { PARAM_VALUE.PHY_MODE_1R1T } {
	# Procedure called to update PHY_MODE_1R1T when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.PHY_MODE_1R1T { PARAM_VALUE.PHY_MODE_1R1T } {
	# Procedure called to validate PHY_MODE_1R1T
	return true
}

proc update_PARAM_VALUE.PHY_MODE_2R2T { PARAM_VALUE.PHY_MODE_2R2T } {
	# Procedure called to update PHY_MODE_2R2T when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.PHY_MODE_2R2T { PARAM_VALUE.PHY_MODE_2R2T } {
	# Procedure called to validate PHY_MODE_2R2T
	return true
}


proc update_MODELPARAM_VALUE.PHY_MODE_1R1T { MODELPARAM_VALUE.PHY_MODE_1R1T PARAM_VALUE.PHY_MODE_1R1T } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.PHY_MODE_1R1T}] ${MODELPARAM_VALUE.PHY_MODE_1R1T}
}

proc update_MODELPARAM_VALUE.PHY_MODE_2R2T { MODELPARAM_VALUE.PHY_MODE_2R2T PARAM_VALUE.PHY_MODE_2R2T } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.PHY_MODE_2R2T}] ${MODELPARAM_VALUE.PHY_MODE_2R2T}
}

