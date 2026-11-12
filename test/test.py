
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from cocotbext.spi import SpiBus, SpiConfig, SpiMaster


@cocotb.test()
async def test_project(dut):

    # Start system clock
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    # Reset DUT
    dut._log.info("Reset")

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0

    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1

    

    # Initialize SPI bus
    spi_bus = SpiBus.from_prefix(dut, prefix="spi", cs_name="cs")

    spi_config = SpiConfig(
        sclk_freq=10000000,
        word_width=16,
        cpol=False,
        cpha=True,
        msb_first=True,
        cs_active_low=True
    )

    spi_master = SpiMaster(spi_bus, spi_config)
    
    # Allow CS_N to settle after reset
    await ClockCycles(dut.clk, 5)
    
    # First transaction
    tx_data = [0x0000, 0x4000, 0x8000, 0xC6B0]

    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")

    # Blocking write: waits until all words have transmitted
    await spi_master.write(tx_data)

    # Retrieve received words
    rx_data = await spi_master.read()

    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")

    assert len(rx_data) == 4
    assert rx_data[0] == 0x0000
    assert rx_data[1] == 0x0000
    assert rx_data[2] == 0x00FF
    assert rx_data[3] == ((tx_data[3] & 0x3FFF) >> 6)

    # Second transaction after CS_N has been idle
    await ClockCycles(dut.clk, 5)

    tx_data = [(0x03A3) << 6]
    dut._log.info(f"TX: {' '.join(f'{num:016b}' for num in tx_data)}")
    await spi_master.write(tx_data)
    rx_data = await spi_master.read()

    dut._log.info(f"RX: {' '.join(f'{num:016b}' for num in rx_data)}")

    assert len(rx_data) == 1
    assert isinstance(rx_data, list)
    assert rx_data[0] == ((tx_data[0] & 0x3FFF) >> 6)
