echo spi0.0 > /sys/bus/spi/drivers/ad9361/unbind 2>/dev/null; echo UNBOUND_SPI=$?
cd /sys/bus/platform/devices
for d in *cf-ad9361-lpc; do echo $d > /sys/bus/platform/drivers/cf_axi_adc/unbind 2>/dev/null; echo "ADC $d = $?"; done
for d in *cf-ad9361-dds-core-lpc; do echo $d > /sys/bus/platform/drivers/cf_axi_dds/unbind 2>/dev/null; echo "DDS $d = $?"; done
echo ===RESULT===
for d in /sys/bus/iio/devices/iio:device*; do echo "$d = $(cat $d/name 2>/dev/null)"; done
echo ===SPI-DRIVER===
readlink /sys/bus/spi/devices/spi0.0/driver
echo ===DONE===