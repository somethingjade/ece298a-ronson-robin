# Design Considerations

Wikipedia says I need shift registers to receive and output.

Recall that shift registers are a bunch of flipflops lined up that
pipelines bits down to the next flipflop per clock cycle.

As SPI MOSI and MISO can only send 1 bit per clock cycle each, if we
want to store values after multiple cycles, we need to use shift
registers.

As such, expect that shift registers can be reset to all 0, and also
that if it is not being clocked (or set otherwise), it should keep it's
values.

Also add tri-state buffers on the wires as otherwise we cannot support
multiple slaves on the same bus (consider this as a scalability option).

This may be implemented using the output enable signals from the top
level.

If rst_n is pulled low, reset the state. Consider the following:

-   Is the reset state all 0?
-   And does the state refer to the shift registers, or something else
    in the spi module?

If cs_n is pulled high, slave should be disconnected from the bus.

If not, logic below is defined and active.

One bit is transfered per spi clock cycle, bidirectional, AKA full
duplex.

Transmission are usually 8 bit words, but for our application we need
more that 8, so maybe commonly 16?

What should we do with the remaining bits? Perhaps use them as a CRC?
But extra logic for data validity is space consuming and also adds
complexity.

If we don't choose 16, and go something more arbitrary like 10, it would
be less conventional and could introduce issues for testing since master
devices probably expect de-facto standards.

For example, suppose the microcontroller can only support whole-byte
transmissions and sends 16 bits, but our design only takes 10 bits
strictly - would our design just suddenly ignore the rest 6 bits?

What would happen if we are sending multiple 10 bit messages padded to
16 bits; would our reciever interpret the 6 padding bits as part of the
next 10 bit message?

I suppose this would also require us to define, in our SPI protocol,
"when" a message might start or end, and other authoritative
characteristics.

In this sense, might it be better that we use a 16 bit message, and have
the SPI slave expect 6 extra bits of padding and do nothing?

MSB is usually sent first, but original SPI specs had an LSB-first
enable bit. We'll ignore this in our implementation.

The clock passed in might be either idle at 0, or idle at 1. In short,
this determines whether you need to read on a +edge or -edge, and also
changes the timing of when you send data.

There is also phase difference expected between the data-bit
transmission-cycle and the spi clk.

e.g. first bit is sent immediately when cs_n is pulled low, subsequent
bits are outputted when clk goes from active-\>idle edge, sampling on
idle-\>active.

e.g. first bit is sent on the first edge of clk AFTER cs_n goes low,
subsequent bits are outputted when clk idle-\>active, sampling
active-\>idle.

Wikipedia says the conversion between the two phase options IS NOT
TRIVIAL, so both host and device should follow the same configurations.

The above configurations are 2/4 possible SPI modes. Refer to online
sources for details.

In Full duplex operation, MISO and MOSI can operate in different SPI
modes.

Does this require both host and device to be writing at the same time on
the same frame (frame refers to 16 bits)?

For example, consider the host is requesting data from the device. Does
the device send that data in the same frame, or in the next?

We'll have the demo board to test the actual chip - what does that
microcontroller support?

Let's assume we're using TT04+ demo board. There's a RP2040 uController,
same used in Rasp Pi PICO.

The demo board can be interacted with using a website GUI, but also a
python SDK that can be used with micro cocotb.

While micropython may have less access to libraries, there still exist
libraries for peripherals like SPI (as advised by AI).

It's almost certain there exists a SPI module that allows us to set the
SPI modes, meaning it should be valid to implement any SPI mode on our
chip.

## Alternatives

Do we need to implement shift registers to receive? While it would make
the most sense from an OOP or modularization perspective, it can be
considered redundant.

Suppose the shift registers stores 16 bits, with 4 padded bits. Other
modules would only need to index the specific flip flop to retreive
values, and outputting would just be assining values to the specific
index, which is quite simple.

But consider the example where to output, the spongent core would need
to load 8 bits into the shift register, then the SR would then feed it
into MISO.

There is redundancy since we don't necessarily need to put 8 bits into
another storage space when the 88 state reg already exist.

An idea we had is to simply remove the need of a shift register in the
SPI module. The bits come in from MOSI and we directly feed it into the
spongent core. Recall that the first stage in SPONGENT is the 88 state
register.

We have to XOR the input into the state registers, but whether we do
this all together or each bit one by one doesn't matter. As such, we can
just pipe out each bit one at a time from MOSI and XOR it directly into
the respective position in the state registers.

How would we differentiate between CTRL bits and data bits, and what do
we do with padding bits?

Since we don't have that many CTRL bits, its highly feasible to treat
the CTRL bits as a Finite State Machine, where depending on the FSM
state (not to be confused with 88 bit state registers), the remaining
data bits will be dealt with necessarily.

For example, if the FSM state requires spongent core to ignore the rest
of the message, then we don't need to process any of the 8 data bits.

If FSM state requires us to feed into spongent core (i.e. a write
command), then after the CTRL bits are read, the remaning 8 data bits
will be fed 1 by 1 into the state registers using XOR. Once we absorb 8
bits, the rest of the padding bits will be ignored.

How are we supposed to figure out when a new message is coming and when
an old message is done?

## Metastability

We also need to consider the fact that signals are not perfectly 0 nor 1
at any given time instance, and that flip flops may show error when
reading values close to clock edges.

It is said that a flip flop may encounter metastability problems if the
data being read changes at the same time as the flip flop samples it on
a clock edge, thus violating t_setup and t_hold (time chunks within the
flipflop response).

This means the value in the flip flop is yet to be determined, but will
stabilize after a while (under the assumption that a while is a short
amount of time).

To accomdate for metastability, it might be nice to use a 2-bit-wide
shift register on both the SPI clock and MOSI. In this situation, the
addition of a second register is simply to add a time delay such that
the first register may stabilize at the next clock.

For example, at clock cycle 1, flip flop 1 becomes unstable, meaning the
output is also unstable. This unstable output is fed to flip flop 2, but
only absorbed by flip flop 2 by clock cycle 2.

However, if we assume that 1 clock cycle is enough for flip flop 1 to
stabilize, then by the time flip flop 2 reads the output of flip flop 1,
the output is already stable. As such, if we were to read the output
from flipflop 2, it would always be stable.

This assumption is not perfect, but may be useful in case of an actual
metastability issue. This use of shift registers is considered a
synchronization chain.

If the SPI clock recieves a synchronization chain, the MOSI line must
also have the same synchronization chain to ensure that the time delay
for both lines are the same (to prevent skew).

## Final Thoughts

Let's consider using SPI mode 0. Sck is considered idle when at a logic
low, and the first bit is outputted immediately when cs_n is pulled low,
then every subsequent bit is outputed on the falling edge of the clock,
and sampled on the rising edge of the clock. There is a non-arbitrary
time delay between when cs_n is pulled low and the first falling edge of
the clock. As such, our system needs to output on both cs_n and the
falling edge of the clock, while also keeping track of which bit to
send.

It would simpler to only track the spi clock edge when outputting bits,
and just have cs_n be required to be pulled low.

It would make more sense for us to consider SPI mode 1, which is output
on rising edge of clock only, sample on falling edge, both of which only
happen after cs_n has pulled low.

The first bit outputed happens on the first rising edge of the clock.
Clock is still considered idle at a logic low.
