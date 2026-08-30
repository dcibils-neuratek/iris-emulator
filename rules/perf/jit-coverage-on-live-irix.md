# JIT coverage collapses on live IRIX: 59%, in 7-instruction regions

First measurements from the `j2 status` coverage counter (R0,
`docs/jitv2_performance_analysis.md`). The headline: **bare-metal and boot
workloads badly overstate how much of a real IRIX session runs compiled**, and
the reason is region length, not codegen quality.

Host: Mac Pro (Late 2013), Xeon E5-1620 v2 (4c/8t, 3.7 GHz), macOS 12.7.6.
Build: `lightning,rex-jit,jitv2,chd`, `RUSTFLAGS=-C target-cpu=native`.
Guest: IRIX on an R5000, 512 MB, COW overlay.

| | boot to login (90 s) | live desktop session |
|---|---:|---:|
| coverage | 83.24% | **59.38%** |
| mean instructions per region entry | 29.4 | **7.1** |
| dispatches | 155 M | 2,067 M |
| exits: complete | 96.7% | **98.9%** |
| exits: fallback | 3.3% | 1.1% |
| functions compiled | 21,815 | 72,087 |
| mega-flushes | 0 | 0 |

The desktop figure is cumulative from launch, so it *includes* that boot; the
steady-state desktop number is therefore somewhat worse than 59.38%, not
better.

## What it means

**Regions are not failing — they are tiny.** 98.9% of dispatches return
`complete`: no exception, no retry, no bail. The compiled code does exactly
what it was asked to do and then hands control straight back, after an average
of seven instructions. Two billion times.

That is region *fragmentation*, and it is a property of the guest code, not of
the compiler. The boot path is long straight-line loops — memory clears, device
polling, `DELAY()` — which is the shape jitv2's region model is happiest with.
A desktop is X11 clients, kernel syscall paths, locking and cache management,
which is dense in the instructions that end a region by construction
(`rules/jitv2/unsupported-instructions.md`).

## Why this reorders the roadmap

With a JIT-vs-interpreter ratio of ~6x on integer code
(`rules/perf/bench-first-numbers.md`), coverage `c` gives a whole-workload
speedup of `1 / (c/6 + (1-c))`:

| coverage | speedup |
|---:|---:|
| 59.4% (measured) | 1.98x |
| 83.2% (boot) | 3.24x |
| 100% | 6x |

At 59.4% the interpreted **40% of instructions is ~80% of the runtime**. The
measured 1.98x also matches the observed status-bar figure on this host
(58-100 MIPS interactive against a ~50 MIPS interpreter baseline), which is
weak independent corroboration that the counter is measuring what it claims.

So the ranking in `docs/jitv2_performance_analysis.md` — R1 (inline memory) at
85% confidence, R3 (region admission) at 70% — is inverted **for this
workload**. R1 makes compiled code faster; compiled code is only 59% of the
picture, and Amdahl caps what that can return. The bigger prize is admission
and, newly, block chaining: at 7.1 instructions per entry, dispatcher
round-trips are being paid two billion times over regions barely longer than
the gate that reaches them. Block chaining is listed as designed-for but not
built (`rules/jitv2/jit-v2-design.md` §6); this is the number that argues for
building it.

Reasoning, not measured: that R3 would actually lengthen regions. It is the
obvious candidate because `CACHE`/`LL`/`SC` are exactly what a kernel does
constantly, but nothing here proves those are the boundaries doing the cutting.
**The next measurement to take is a histogram of *why* regions end** — the exit
buckets say how compiled code left, not why the analyzer stopped walking.

## Reproducing

`j2 status` reads through the executor, so it fails with
`CPU thread holds the executor lock; try 'cpu stop' first` on a busy CPU. An
idle-parked desktop happens to answer anyway (the CPU thread has released the
lock), which makes this look intermittent. Always:

```
stop
j2 status
start
```

macOS has no `telnet` since 10.13 — use `nc 127.0.0.1 8888`, or type at the
`>` prompt in the terminal that launched iris. Stopping the CPU freezes the
guest for as long as you take; it resumes cleanly on `start`.

## Caveats

- One host, one guest, one session. No repeats.
- R5000 only. The R4400's L2 model changes the memory picture substantially
  (`rules/perf/bench-first-numbers.md` §2) and might change coverage too.
- "Desktop session" here included Software Manager, `winterm`, `jot` and a
  console — interactive and I/O-heavy, not a compute workload. A build or a
  demo would likely look different, possibly much better.
