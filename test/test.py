import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge
from cocotbext.spi import SpiBus, SpiConfig, SpiMaster
from cocotb.triggers import ClockCycles
from cocotb.types import Logic



@cocotb.test()
async def test_project(dut):
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    # 2. Reset the DUT    
    dut._log.info("Reset")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    
    # THIS WAIT IS MANDATORY TO PREVENT CS_N FROM PULLING LOW WHILE RST_N IS LOW
    await ClockCycles(dut.clk, 5)

    # Create the bus by tracking any signals that prefix with "spi"
    # Should be named spi_sclk, spi_cs, spi_mosi, spi_miso in the test bench tb.v
    spi_bus = SpiBus.from_prefix(dut, prefix="spi")
    
    # Configure the SPI Protocol (e.g., Mode 1: CPOL=0, CPHA=1)
    spi_config = SpiConfig(
        sclk_freq=25000000, # Should be x4 slower than device clock, or says our requirements
        word_width=16,
        cpol=False,
        cpha=True,
        msb_first=True,
        cs_active_low=True
    )

    # Instantiate the SPI Master driver
    spi_master = SpiMaster(spi_bus, spi_config)

    # Perform a Full-Duplex Transfer of 4 messages back to back
    tx_data = [0x0000, 0x4000, 0x8000, 0xc000] # The data represents the 4 possible FSM states of the spongent core
    dut._log.info(f"{' '.join(f'{num:b}' for num in tx_data)}")
    
    # This coroutine blocks until the entire SPI transaction finishes
    spi_master.write_nowait(tx_data)

    await spi_master.wait()
    
    # Read back the full-duplex response bytes from the receive buffer
    # Note that during the write, both master and slave are writing to the bus simultaneously
    rx_data = await spi_master.read()
    
    if (isinstance(rx_data, type(None))):
        assert False, "rx_data was none!"
    dut._log.info(f"{' '.join(f'{num:b}' for num in rx_data)}")
    
    # These assertions are to test whether the 6-bit shift register delay behavior iz correct
    assert rx_data[0] == 0x00FF
    assert rx_data[1] == 0x00FF
    assert rx_data[2] == 0x00FF
    assert rx_data[3] == 0x00FF
    
    # While writing data back to back, between message frames, the cs_n signal rises and falls
    # extremely fast, turning into a simple impulse rather than held high for a few device clck cycles
    # The following is to test a write to the slave after cs_n has been held high for a while
    await ClockCycles(dut.clk, 5)
    
    tx_data = [0]
    spi_master.write_nowait(tx_data)
    await spi_master.wait()
    rx_data = await spi_master.read()
    print(f"{rx_data}")
    assert rx_data[0] == 0x00FF
