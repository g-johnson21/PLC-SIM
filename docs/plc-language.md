# Draco PLC language and runtime contract

**This is not a replica of the real stand's NI cRIO-9047 LabVIEW environment.** It is a
deliberately small, IEC 61131-3–*flavoured* language family built for training: the control
habits it teaches (hysteresis, latching, interlocks, sequence steps, abort chains) transfer to
the real stand, but the syntax, the editor and the exact function-block library do not. Where
this document and IEC 61131-3 disagree, this document wins for the simulator.

Implementation: `backend/draco_sim/plc/` (pure Python 3.13, no third-party dependencies).
Audience: the IDE frontend, the scan-loop task, and anyone writing programs for the stand.

Contents: [data model](#1-data-model) · [function blocks](#2-standard-function-blocks) ·
[functions](#3-standard-functions) · [Structured Text](#4-structured-text-st) ·
[Ladder JSON](#5-ladder-diagram-ld-json-document) · [SFC JSON](#6-sequential-function-chart-sfc-json-document) ·
[runtime API](#7-runtime-api) · [errors and faults](#8-compileerror-and-plcfault)

---

## 1. Data model

### 1.1 Types

| Type | Representation | Notes |
|---|---|---|
| `BOOL` | Python `bool` | |
| `INT` | signed 32-bit | **wraps** on overflow (two's complement). IEC's `INT` is 16-bit; this engine makes `INT` and `DINT` the same 32-bit type, and documents the difference rather than silently truncating. |
| `DINT` | signed 32-bit | identical to `INT`; both names accepted |
| `REAL` | IEEE-754 float64 | `LREAL` is accepted as an alias |
| `TIME` | float64 **seconds** | literals `T#500ms`, `T#1s500ms`, `T#2.5s`, `T#-5s`; units `d h m s ms us ns`; `TIME#` prefix also accepted |
| `STRING` | Python `str` | single-quoted, `$`-escapes. Assignment and `=`/`<>` only — no string functions |

Integer arithmetic (`+ - * /`) wraps to the 32-bit range. Counter `CV` values **saturate**
instead of wrapping (IEC requires this). `REAL` overflow produces `inf` rather than a fault;
division by zero, `SQRT` of a negative number and `LN`/`LOG` of a non-positive number are
runtime faults.

### 1.2 Variables and scope

| Block | Lifetime | Shared |
|---|---|---|
| `VAR` | persists across scans | per program |
| `VAR_RETAIN` | identical to `VAR` (there is no power-fail memory to retain to) | per program |
| `VAR_GLOBAL` | persists across scans | across every program in one `PlcRuntime` |
| `VAR ... CONSTANT` | read-only, needs an initial value | per program |

A program may only reference a global it declares itself. To share one, declare it in each
program with the **same type**; the initial value may be given in one program and omitted in the
others. Two programs giving the same global different explicit initial values is a `ValueError`
at `PlcRuntime` construction.

Initial values must be literal constants (optionally signed). Uninitialised variables start at
`FALSE` / `0` / `0.0` / `T#0s` / `''`.

### 1.3 Name resolution

Identifiers are **case-insensitive** (`PT3`, `pt3` and `Pt3` are one name) and case-preserving
(the declared spelling is what `variables()` and the watch view report). Resolution order:

1. local variable (`VAR` / `VAR_RETAIN` / `CONSTANT`)
2. global variable (`VAR_GLOBAL`)
3. tag (`TagSpec.name`)
4. system variable

An unknown identifier is a compile error. Declaring a variable whose name matches a tag or a
system variable is also a compile error — shadowing a sensor name is never what an operator
meant. Tags are referenced directly by name; there is no `%I`/`%Q` addressing.

### 1.4 Tags

```python
@dataclass(frozen=True)
class TagSpec:
    name: str        # e.g. "PT3"
    direction: str   # "in" | "out"
    dtype: str       # "REAL" | "BOOL"  (INT/DINT/TIME/STRING also accepted)
    units: str       # e.g. "psi"
```

`direction="in"` tags are **read-only** inside programs: assigning to one, or driving it with a
coil, is a compile error. `direction="out"` tags are the output image; they hold their value
until something writes them. `draco_sim.plc.DRACO_TAGSPECS_PLACEHOLDER` is the stand-in list
(18 PTs, 8 TCs, 5 LCs, `THRUST`, and 14 BOOL outputs) until `TagDatabase.plc_specs()` lands.

### 1.5 System variables (read-only)

| Name | Type | Meaning |
|---|---|---|
| `SYS_ABORT` | `BOOL` | abort latched (`trigger_abort()` until `clear_abort()`) |
| `SYS_SCAN_TIME` | `REAL` | `dt` of the current scan, seconds |
| `SYS_FIRST_SCAN` | `BOOL` | true during the first scan after construction or `reset()` |
| `SYS_TIME` | `REAL` | seconds of simulated time at the **start** of the current scan |

### 1.6 Time and determinism

Nothing in the engine reads the wall clock. Every timer, every step timer and `SYS_TIME`
advances only by the `dt` passed to `scan()`. Time is accumulated with Neumaier compensated
summation, so 50 scans of `dt=0.01` give exactly `0.5 s` rather than `0.49999999999999994`;
function-block comparisons additionally allow a `1e-9 s` tolerance. Two runtimes fed the same
programs, the same `write_inputs()` and the same sequence of `dt` values produce bit-identical
outputs. (`ScanResult.duration_s` is measured with `perf_counter` — it is a diagnostic and can
never influence program behaviour.)

---

## 2. Standard function blocks

Declared as instances (`VAR t1 : TON; END_VAR`), invoked as statements, read through their
fields (`t1.Q`, `t1.ET`). Instance state persists across scans and is part of `variables()`.

| Block | Inputs | Outputs | Behaviour |
|---|---|---|---|
| `TON` | `IN`, `PT` | `Q`, `ET` | on-delay: `Q` after `IN` has been true for `PT` |
| `TOF` | `IN`, `PT` | `Q`, `ET` | off-delay: `Q` drops `PT` after `IN` goes false |
| `TP` | `IN`, `PT` | `Q`, `ET` | pulse of length `PT` on a rising edge of `IN`; retriggering during the pulse is ignored |
| `CTU` | `CU`, `R`, `PV` | `Q`, `CV` | `CV` +1 per rising edge of `CU`; `R` dominates; `Q := CV >= PV` |
| `CTD` | `CD`, `LD`, `PV` | `Q`, `CV` | `CV` −1 per rising edge of `CD`; `LD` loads `PV`; `Q := CV <= 0` |
| `CTUD` | `CU`, `CD`, `R`, `LD`, `PV` | `QU`, `QD`, `CV` | `R` dominates `LD`; simultaneous `CU`/`CD` edges cancel |
| `R_TRIG` | `CLK` | `Q` | one scan on a rising edge |
| `F_TRIG` | `CLK` | `Q` | one scan on a falling edge (no edge on power-up) |
| `SR` | `S1`, `R` | `Q1` (alias `Q`) | set-dominant latch |
| `RS` | `S`, `R1` | `Q1` (alias `Q`) | reset-dominant latch |

**Timer convention.** `ET` is `0` on the scan the timer starts and accumulates `dt` from the
next scan, so with `dt = 10 ms` a `TON` with `PT := T#500ms` sets `Q` on the 51st scan after the
edge (the starting scan counted as the first). SFC step timers use the same convention. `PT = 0`
makes `TON` fire immediately and suppresses `TP`/`TOF` delays entirely.

---

## 3. Standard functions

`ABS  MIN  MAX  LIMIT  SEL  MUX  SQRT  EXP  LN  LOG  SIN  COS  TAN  TRUNC  REAL_TO_INT
INT_TO_REAL  BOOL_TO_INT  TIME_TO_REAL  REAL_TO_TIME`

* `MIN`/`MAX` take two or more arguments; `LIMIT(MN, IN, MX)`; `SEL(G, IN0, IN1)` returns `IN1`
  when `G`; `MUX(K, IN0, IN1, …)` selects by zero-based `K` and **faults** if `K` is out of range.
* `LN` is natural log, `LOG` is base 10. Trig is in radians.
* `TRUNC` truncates toward zero; `REAL_TO_INT` rounds to nearest with ties to even.
* `TIME_TO_REAL` yields seconds, `REAL_TO_TIME` takes seconds.
* There is no way to define your own functions or function blocks.

---

## 4. Structured Text (ST)

### 4.1 Grammar

```ebnf
program        = [ "PROGRAM" identifier ] { var_block } stmt_list [ "END_PROGRAM" ] ;
var_block      = ( "VAR" | "VAR_GLOBAL" | "VAR_RETAIN" ) [ "CONSTANT" ]
                 { var_decl } "END_VAR" ;
var_decl       = identifier { "," identifier } ":" type_name [ ":=" constant ] ";" ;
type_name      = "BOOL" | "INT" | "DINT" | "REAL" | "LREAL" | "TIME" | "STRING" | fb_type ;
fb_type        = "TON" | "TOF" | "TP" | "CTU" | "CTD" | "CTUD"
               | "R_TRIG" | "F_TRIG" | "SR" | "RS" ;
constant       = [ "+" | "-" ] literal ;

stmt_list      = { statement } ;
statement      = assignment | fb_invocation | if_stmt | case_stmt | for_stmt
               | while_stmt | repeat_stmt | "EXIT" ";" | "RETURN" ";" | ";" ;
assignment     = identifier [ "." identifier ] ":=" expression ";" ;
fb_invocation  = identifier "(" [ argument { "," argument } ] ")" ";" ;
argument       = [ identifier ":=" ] expression ;
if_stmt        = "IF" expression "THEN" stmt_list
                 { "ELSIF" expression "THEN" stmt_list }
                 [ "ELSE" stmt_list ] "END_IF" [ ";" ] ;
case_stmt      = "CASE" expression "OF" { case_element }
                 [ "ELSE" stmt_list ] "END_CASE" [ ";" ] ;
case_element   = case_label { "," case_label } ":" stmt_list ;
case_label     = [ "-" ] integer [ ".." [ "-" ] integer ] ;
for_stmt       = "FOR" identifier ":=" expression "TO" expression [ "BY" expression ]
                 "DO" stmt_list "END_FOR" [ ";" ] ;
while_stmt     = "WHILE" expression "DO" stmt_list "END_WHILE" [ ";" ] ;
repeat_stmt    = "REPEAT" stmt_list "UNTIL" expression "END_REPEAT" [ ";" ] ;

expression     = xor_expr { "OR" xor_expr } ;
xor_expr       = and_expr { "XOR" and_expr } ;
and_expr       = eq_expr { ( "AND" | "&" ) eq_expr } ;
eq_expr        = rel_expr { ( "=" | "<>" ) rel_expr } ;
rel_expr       = add_expr { ( "<" | ">" | "<=" | ">=" ) add_expr } ;
add_expr       = term { ( "+" | "-" ) term } ;
term           = unary { ( "*" | "/" | "MOD" ) unary } ;
unary          = ( "-" | "+" | "NOT" ) unary | power ;
power          = primary [ "**" unary ] ;
primary        = literal | "(" expression ")" | function_call
               | identifier [ "." identifier ] ;
function_call  = identifier "(" [ expression { "," expression } ] ")" ;
literal        = integer | real | time | string | "TRUE" | "FALSE" ;
integer        = digits | ( "2" | "8" | "16" ) "#" based_digits ;   (* "_" allowed *)
```

Operator precedence, tightest first: `**`, unary `-`/`NOT`, `* / MOD`, `+ -`,
`< > <= >=`, `= <>`, `AND` (`&`), `XOR`, `OR`. `**` is right-associative and binds tighter than
unary minus, so `-2 ** 2` is `-4`.

Comments: `(* ... *)` (nestable) and `// to end of line`. Keywords are case-insensitive.

### 4.2 Semantics and restrictions

* **Type rules.** `AND`/`OR`/`XOR`/`NOT` take `BOOL` only — there are no bitwise operators.
  `MOD` takes integers only and takes the sign of the dividend. `/` on two integers is integer
  division truncating toward zero; any `REAL` operand makes it real division. `**` always yields
  `REAL`. `TIME ± TIME → TIME`, `TIME * number → TIME`, `TIME / number → TIME`,
  `TIME / TIME → REAL`. Comparisons need both sides numeric, both `TIME`, both `STRING`, or
  (for `=`/`<>`) both `BOOL`.
* **Assignment.** `INT → REAL` is implicit. `REAL → INT`, `TIME → REAL` and `BOOL → INT` are
  compile errors that name the conversion function to use.
* **Function blocks.** `t1(IN := x, PT := T#1s);` then `y := t1.Q;`. Positional arguments are
  accepted in declaration order. Inputs not given in a call keep their previous value.
  `t1.PT := x;` (assignment to an input field) is also allowed.
* **`CASE`** selectors must be `INT`/`DINT`. Overlapping labels are a compile error. No matching
  branch and no `ELSE` does nothing — that is IEC behaviour, not a fault.
* **Loops** are capped at **10 000 iterations each**; exceeding the cap raises a runtime fault
  (kind `loop`) rather than hanging the scan. `EXIT` leaves the innermost loop; `EXIT` outside a
  loop is a compile error. `RETURN` ends the program's scan.
* **Not supported:** arrays, structs, enumerations, pointers, user-defined functions and
  function blocks, `VAR_INPUT`/`VAR_OUTPUT`/`VAR_IN_OUT`, `AT %I*` addressing, `EN`/`ENO`.

### 4.3 Worked example

```iecst
PROGRAM bangbang_lox
VAR_GLOBAL
    setpoint : REAL := 904.0;   (* psi, operator-set at runtime *)
    deadband : REAL := 15.0;
    bb_lox_enable : BOOL := FALSE;
END_VAR
VAR
    was_enabled : BOOL := FALSE;   (* bb_lox_enable on the previous scan *)
END_VAR
    IF bb_lox_enable THEN
        IF PT3 < setpoint - deadband THEN
            S1 := TRUE;
        ELSIF PT3 > setpoint + deadband THEN
            S1 := FALSE;
        END_IF;   // no ELSE: inside the band S1 holds
    ELSIF was_enabled THEN
        S1 := FALSE;   (* disabled this scan: close once, then S1 is the GC's (D17) *)
    END_IF;
    was_enabled := bb_lox_enable;
END_PROGRAM
```

---

## 5. Ladder Diagram (LD) JSON document

### 5.1 Document

```json
{
  "version": 1,
  "language": "LD",
  "name": "bangbang_fuel",
  "description": "optional free text",
  "vars": [ VarDecl, ... ],
  "rungs": [ Rung, ... ]
}
```

`version` and `name` are required (`name` may instead be supplied as `compile_program(...,
name=...)`). `version` is the schema version this engine speaks — currently `1`
(`draco_sim.plc.LD_VERSION`).

**VarDecl** (shared with SFC):

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | identifier |
| `type` | yes | `BOOL` `INT` `DINT` `REAL` `TIME` `STRING`, or a function-block type |
| `scope` | no | `"VAR"` (default), `"VAR_GLOBAL"`, `"VAR_RETAIN"` |
| `init` | no | literal: JSON number/boolean, or a `"T#…"` string |
| `comment` | no | free text, ignored by the engine |

**Rung**: `{"id": "r2", "comment": "...", "logic": Network}`. Rungs execute in array order,
each starting with power true at the left rail.

### 5.2 Networks

A `Network` is either a container or an element:

```json
{"type": "series",   "elements": [Network, ...]}     // left to right, power threaded
{"type": "parallel", "branches": [Network, ...]}     // same input power, OR of outputs
```

Power-flow rules:

* **Series** threads the outgoing power of one element into the next.
* **Parallel** gives every branch the same incoming power and ORs their outgoing power.
  **There is no short-circuit evaluation** — every branch runs every scan, so coils, timers and
  counters inside parallel branches always execute. This is what lets coils sit in parallel.
* Coils and blocks **pass power through** (a coil's outgoing power equals its incoming power),
  so elements may follow a coil on the same rung.
* Edge contacts (`P`/`N`) update their edge memory every scan regardless of incoming power, and
  output `power AND edge`.

### 5.3 Operands

Every operand field uses one grammar:

| JSON | Means |
|---|---|
| `"PT13"` | reference to a variable or tag (any string that is not a TIME literal) |
| `"T#500ms"` | a `TIME` literal (`#` cannot appear in an identifier, so this is unambiguous) |
| `904.0`, `3`, `true` | a `REAL`, `INT`, `BOOL` literal |
| `{"var": "PT13"}` | explicit reference |
| `{"const": 904.0}` | explicit literal |
| `{"time": "T#1s500ms"}` | explicit `TIME` literal |

Destination fields (`operand` of a coil, `dst`, `q`, `et`, `cv`) must name a writable variable or
an output tag; writing an input tag is a compile error.

### 5.4 Elements

Every element accepts optional `"id"` (a stable string the IDE can highlight; ids must be unique
within a document and are what timer/counter edge memory is keyed by) and `"comment"`.

| `type` | Fields | Outgoing power |
|---|---|---|
| `contact` | `kind`: `NO` `NC` `P` `N`; `operand` (BOOL) | `power AND` contact state/edge |
| `coil` | `kind`: `COIL` `SET` `RESET` `NEGATED`; `operand` (writable BOOL) | unchanged (`power`) |
| `timer` | `fb`: `TON` `TOF` `TP`; `pt` (TIME); optional `instance`, `in`, `q`, `et` | the timer's `Q` |
| `counter` | `fb`: `CTU` `CTD`; `pv` (INT); optional `instance`, `cu`/`cd`, `reset`/`load`, `q`, `cv` | the counter's `Q` |
| `compare` | `op`: `GT` `GE` `EQ` `NE` `LE` `LT`; `a`, `b` | `power AND (a op b)` |
| `move` | `src`, `dst` | unchanged; writes only when powered |
| `math` | `op`: `ADD` `SUB` `MUL` `DIV`; `a`, `b`, `dst` | unchanged; computes only when powered |

Coil kinds: `COIL` writes power, `NEGATED` writes `NOT power`, `SET` writes true only while
powered, `RESET` writes false only while powered.

Timer/counter blocks take their drive input from rung power unless `in` (timers) or `cu`/`cd`
(counters) names an operand. `instance` names the function-block instance so it appears in the
watch view; if omitted, a hidden instance keyed by the element id is created. Declaring the same
instance name in `vars` with the matching FB type is allowed and equivalent.

`DIV` by zero while powered is a runtime fault.

### 5.5 Worked rung

```json
{
  "id": "r3",
  "comment": "Enabled and above the band, or disabled on this scan: close it",
  "logic": {
    "type": "series",
    "elements": [
      {
        "id": "r3.par",
        "type": "parallel",
        "branches": [
          {"type": "series", "elements": [
            {"id": "r3.en", "type": "contact", "kind": "NO", "operand": "bb_fuel_enable"},
            {"id": "r3.gt", "type": "compare", "op": "GT", "a": "PT13", "b": "hi"}
          ]},
          {"type": "series", "elements": [
            {"id": "r3.dis", "type": "contact", "kind": "NC", "operand": "bb_fuel_enable"},
            {"id": "r3.was", "type": "contact", "kind": "NO", "operand": "was_enabled"}
          ]}
        ]
      },
      {"id": "r3.rst", "type": "coil", "kind": "RESET", "operand": "S2"}
    ]
  }
}
```

`ladder_to_text(doc)` renders exactly this rung as:

```text
Rung 0 [r3]  Enabled and above the band, or disabled on this scan: close it
        bb_fuel_enable    PT13 > hi        S2
  |--+-------] [-------------[GT]------+--(R)----|
     |  bb_fuel_enable    was_enabled  |
     +-------]/[--------------] [------+
```

Rung `r4` (`bb_fuel_enable` → `COIL was_enabled`) follows it, so `was_enabled` holds the previous
scan's enable. The loop therefore writes S2 only while enabled, plus once on the scan it is
disabled (decisions.md D17).

```text
```

The renderer is one-way (document → text) and exists for debugging and documentation; there is
no text-to-ladder parser.

---

## 6. Sequential Function Chart (SFC) JSON document

### 6.1 Document

```json
{
  "version": 1,
  "language": "SFC",
  "name": "hotfire",
  "description": "optional free text",
  "autostart": false,
  "abort_step": "ABORT",
  "vars": [ VarDecl, ... ],
  "steps": [ Step, ... ],
  "transitions": [ Transition, ... ]
}
```

`autostart` (default `false`) makes the chart begin at its initial step on construction and
`reset()`; otherwise it is constructed stopped and must be started with
`runtime.start_sfc(name)`. `abort_step` names the head of the abort chain, or is absent.

**Step**

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | identifier, unique in the document, and must not collide with a variable or tag |
| `initial` | exactly one step | `true` on the step the chart starts at |
| `actions` | no | list of Action, executed in array order |
| `id`, `comment` | no | IDE metadata |

**Action**

| Field | Required | Meaning |
|---|---|---|
| `qualifier` | no (default `N`) | `N` `S` `R` `P` `P0` `D` |
| `body` | no | Structured Text **statement list** (no `PROGRAM`/`VAR` blocks) |
| `name` | no | label used to pair `S` with `R` |
| `delay` | for `D` | `"T#…"` string or seconds |
| `id`, `comment` | no | IDE metadata |

**Transition**

| Field | Required | Meaning |
|---|---|---|
| `from` | yes | step name, or list of step names (simultaneous convergence) |
| `to` | yes | step name, or list of step names (simultaneous divergence) |
| `condition` | yes | ST **boolean expression** |
| `id`, `comment` | no | IDE metadata |

Action bodies and transition conditions are compiled by the same ST compiler with the same
variables and tags, plus step access: `StepName.X` (BOOL, active) and `StepName.T` (TIME, since
activation).

### 6.2 Evolution rules

Once per scan, a running chart does exactly this:

1. **Advance step timers.** Every active step that has already run its entry actions gets
   `T := T + dt`. A step activated during this scan has `T = 0` for the whole of it.
2. **Evaluate transitions**, in document order, against the step state as it is at the start of
   the chart's execution. A transition is *enabled* when **all** of its `from` steps are active
   (that is the AND of a simultaneous convergence), none of them has already been consumed by an
   earlier transition this scan, and none of them was activated during this scan — **a step
   activated this scan does not evaluate its outgoing transitions until the next scan.**
   For an alternative divergence (several transitions out of one step) the **first true
   transition in document order wins**; that is the "left to right" rule.
3. **Commit** in one step: every `from` step of every firing transition is deactivated, then
   every `to` step is activated with `T = 0`.
4. **Run actions**, in this order:
   1. entry actions of steps activated *before* this scan's evolution (`start_sfc`, `trigger_abort`)
   2. `P0` (exit) actions of steps deactivated by this scan's commit
   3. `P` / `S` / `R` (entry) actions of steps activated by this scan's commit
   4. `N` and `D` actions of every currently active step, in step document order

Loops back to earlier steps are just transitions whose `to` precedes their `from`.

### 6.3 Action qualifiers

| Qualifier | When the body runs |
|---|---|
| `N` | every scan while the step is active |
| `P` | once, on the scan the step becomes active |
| `P0` | once, on the scan the step becomes inactive |
| `S` | once on entry; the action `name` is recorded in the chart's stored-action list |
| `R` | once on entry; removes the matching `name` from the stored-action list |
| `D` | every scan while the step is active **and** `T >= delay` |

`S` and `R` are pulses in this engine, not continuously re-executed actions: an output written by
an `S` action stays written because the output image holds it, and a later `R` action writes it
back. The stored-action list is bookkeeping for the IDE (`sfc_state()["…"]["stored_actions"]`) and
for readers of the chart; it does not by itself drive outputs.

### 6.4 Abort model

`runtime.trigger_abort()` latches the abort immediately (`abort_active()` and `SYS_ABORT` become
true) and applies it at the top of the **next** `scan()`:

* every active step of **every** chart in the runtime is deactivated — **no `P0` exit actions
  run**, because an abort is not a normal step exit;
* every chart that declares an `abort_step` is started at that step (whether or not it was
  running), with `T = 0`, and its entry actions run in that same scan;
* a chart with no `abort_step` simply halts with no active steps;
* until `clear_abort()`, only transitions whose `from` steps all lie in the **abort chain** —
  the set of steps reachable from `abort_step` — may fire. The safing chain therefore runs
  normally while the normal chain stays frozen, and an SFC can never advance past an abort.

**A latched abort gates every sequence, including ones that were not running when it latched.**
While `abort_active()` is true, `start_sfc(name)` **raises `PlcStateError`** and starts nothing —
it is never silently ignored. Without this, an operator or a UI could arm a fresh sequence into a
stand that is mid-safing and drive valves that the abort chain had just closed.

`clear_abort()` drops the latch and the transition block, and does nothing else: it starts, stops
and restarts no chart, so every chart stays exactly where the abort left it. Re-arming is
explicit — normally `clear_abort()`, then `reset()` (which returns variables, charts and the
output image to their construction state and clears the latch itself), then `start_sfc(name)`.
The simulator's scan loop does not wait for an operator. It calls `clear_abort()` and stops the
charts by itself once every abort chain is complete, without `reset()` (`docs/runtime.md` §3).

Non-SFC programs keep scanning during an abort — a PLC scan does not stop. Gating regulation is
the scan loop's job: either test `SYS_ABORT` in the program, or call
`runtime.set_program_enabled(name, False)`.

### 6.5 Worked chart (excerpt of `hotfire.sfc.json`)

The hotfire procedure (`docs/decisions.md` D12) runs T+0.00 PB2 open, T+0.50 PB4 open, T+8.00
PB2 close, T+8.50 PB4 close, T+8.70 S4 and S5 open, T+11.70 S4 and S5 close. Its first three
commands:

```json
{
  "vars": [{"name": "t_start", "type": "REAL", "scope": "VAR"}],
  "steps": [
    {"name": "START", "initial": true, "actions": [
      {"qualifier": "P", "body": "t_start := SYS_TIME - 0.000001;"}]},
    {"name": "OPEN_LOX_MAIN", "actions": [
      {"qualifier": "S", "name": "PB2", "body": "PB2 := TRUE;"}]},
    {"name": "OPEN_FUEL_MAIN", "actions": [
      {"qualifier": "S", "name": "PB4", "body": "PB4 := TRUE;"}]},
    {"name": "CLOSE_LOX_MAIN", "actions": [
      {"qualifier": "R", "name": "PB2", "body": "PB2 := FALSE;"}]}
  ],
  "transitions": [
    {"from": "START",          "to": "OPEN_LOX_MAIN",  "condition": "TRUE"},
    {"from": "OPEN_LOX_MAIN",  "to": "OPEN_FUEL_MAIN", "condition": "SYS_TIME - t_start >= 0.5"},
    {"from": "OPEN_FUEL_MAIN", "to": "CLOSE_LOX_MAIN", "condition": "SYS_TIME - t_start >= 8.0"}
  ]
}
```

At `dt = 10 ms`, `start_sfc("hotfire")` followed by scans puts `PB2` true on scan 1, `PB4` true
on scan 51 and `PB2` false on scan 801. On scan 1 the `START` transition fires, `START`'s entry
action runs because `start_sfc` activated it before the scan (§6.2, rule 4.1), and then
`OPEN_LOX_MAIN`'s entry action runs. `t_start` therefore holds `SYS_TIME` at T+0.

Every timed transition compares `SYS_TIME - t_start` with the procedure's T+, instead of using a
step timer such as `OPEN_LOX_MAIN.T >= T#500ms`. A step timer starts at its own step's activation,
so a duration that is not a whole number of scans is rounded up once per step, and the rounding
adds up along the chain. Measuring against one `t_start` rounds each command once, at any scan
rate. The 1 µs margin absorbs floating-point rounding in the subtraction. Without it, a T+ that
falls exactly on a scan boundary sometimes fired a scan late.

---

## 7. Runtime API

```python
from draco_sim.plc import (TagSpec, DRACO_TAGSPECS_PLACEHOLDER, CompileError, PlcFault,
                           PlcStateError, CompiledProgram, PlcRuntime, ScanResult,
                           compile_program, compile_file, ladder_to_text)
```

### 7.1 Lifecycle

```python
programs = [compile_program(src, "ST", tags),          # or "LD" / "SFC" with a dict or JSON text
            compile_file("examples/hotfire.sfc.json", tags)]
rt = PlcRuntime(tags, programs)      # programs run in list order, every scan
rt.write_inputs({"PT3": 904.2})      # sensor image
result = rt.scan(0.01)               # one scan, dt in seconds
outputs = rt.read_outputs()          # {"S1": True, ...}
```

```python
compile_program(source: str | dict, language: Literal["ST","LD","SFC"],
                tags: list[TagSpec], *, name: str | None = None) -> CompiledProgram
compile_file(path, tags, *, name=None, language=None) -> CompiledProgram
```
`compile_file` infers the language from `.st` / `.ld.json` / `.sfc.json`. `CompiledProgram`
exposes `.name`, `.language`, `.locals`, `.globals`, `.variable_count`, `.is_sfc` and
`.output_writes`.

`output_writes: frozenset[str]` is the set of output tags the program contains a write to,
recorded by the compiler as each destination resolves: an ST assignment (including inside SFC
action bodies), an LD coil, or an LD math/move destination. It is a static fact about the code —
a tag is in the set if any branch can write it, whether or not that branch ever runs — and it
is empty for a program that drives no valve. The scan loop uses it to infer a program's role
when none is given (`docs/runtime.md` §1, "Roles"). Contrast `ScanResult.outputs_written` (§7.3), which
is what the running programs actually wrote during one scan.

`abort_writes: frozenset[str]` is the same record restricted to an SFC's abort chain: the output
tags written by the actions of the `abort_step` and of every step reachable from it (§6.4). It is
empty for a chart without an `abort_step` and for every non-SFC program. A tag a chart writes in
a normal step but never in its abort chain is in `output_writes` and not in `abort_writes`. While
an abort is latched the scan loop leaves exactly these tags to the abort chains and drives every
other output to its fail-safe state (`docs/runtime.md` §2).

**Scan order.** The runtime executes programs in the order given, so the scan loop gets the
required ordering (auto-abort monitor → sequencer → regulation) by constructing the runtime with
the programs in that order. `trigger_abort()` is applied before any program runs.

### 7.2 Methods

| Method | Behaviour |
|---|---|
| `write_inputs(mapping)` | writes `"in"` tags; unknown tag or an `"out"` tag raises `ValueError`; values are coerced to the tag dtype; forced tags keep the forced value |
| `scan(dt_s) -> ScanResult` | one scan; never raises for program errors |
| `read_outputs() -> dict` | the whole output image |
| `read_inputs() -> dict` | the input image actually seen by programs (forces applied) |
| `trigger_abort()` | latch the abort; applied to every chart at the top of the next scan (§6.4) |
| `clear_abort()` | drop the latch and the transition block; starts, stops and restarts nothing |
| `abort_active()` | is the latch set |
| `start_sfc(name)` | start a chart at its initial step. **Raises `PlcStateError` while `abort_active()`** — an abort gates every sequence, including ones not running when it latched. `ValueError` if the program is unknown or is not an SFC |
| `stop_sfc(name)` | deactivate every step (no exit actions, outputs hold). Always permitted |
| `sfc_state() -> dict` | per chart: `active_steps`, `step_times`, `aborted`, plus `running` and `stored_actions` |
| `variables() -> dict` | per program: locals, its globals, FB fields (`t1.Q`, `t1.ET`), and for charts `Step.X` / `Step.T` |
| `globals()` / `write_globals(mapping)` | read / set `VAR_GLOBAL` values from outside (operator setpoints, enables) |
| `force(name, value)` / `unforce(name)` / `forced()` | see §7.4 |
| `faults()` / `clear_faults()` / `halted_programs()` | see §7.5 |
| `set_program_enabled(name, bool)` / `program_enabled()` | skip a program in the scan; its outputs hold |
| `reset()` | cold restart: variables to initial values, charts back to construction state (`autostart` re-applied), output image cleared, faults **and the abort latch** cleared, `SYS_TIME` and the scan counter to zero. Forces are kept and re-applied |
| `scan_index` / `sim_time_s` | scan counter (first scan is 1) and accumulated simulated seconds |

### 7.3 ScanResult

```python
@dataclass
class ScanResult:
    scan_index: int            # 1-based
    dt_s: float
    sim_time_s: float          # simulated time after this scan
    faults: list[PlcFault]     # faults raised during this scan
    outputs_changed: dict      # only the output tags whose value changed this scan
    duration_s: float          # wall-clock cost of the scan (diagnostic only)
    outputs_written: frozenset[str]   # output tags an enabled program wrote this scan
```

`outputs_written` is what the scan loop arbitrates on (`docs/runtime.md` §2): it is
the set of output tags that a running program *assigned* during this scan, whether or
not the value changed, so a regulation loop that re-writes `S1 := FALSE` every scan is
known to own S1. `outputs_changed` cannot answer that. Recording is on only while a
program body executes, so `force()` and external edits are not counted; a program that
faults is rolled back and contributes nothing. Conditional writes behave exactly as
the program reads: `bangbang_lox.st` writes S1 on the scans its `IF`/`ELSIF` chain
takes a branch, plus once on the scan its enable goes false. It writes nothing while
the reading sits inside the hysteresis band or the loop stays disabled. An LD `SET`/`RESET`
coil writes only on the scans its rung has power.

### 7.4 Forcing

`force(name, value)` pins a value. `name` may be an input tag, an output tag, a global variable,
or a program-local variable written `"program.variable"`. Forced values are re-applied at the
start and the end of every scan, so a program may write a forced variable and see its own write
within that scan, but the force wins at every scan boundary. A forced input tag overrides
`write_inputs()` until `unforce()`, which restores the last written value. System variables and
function-block instances cannot be forced. `forced()` returns `{name: value}`.

### 7.5 Faults

A runtime fault (division by zero, `MUX` out of range, `SQRT` of a negative number, a loop
exceeding 10 000 iterations, or an internal engine error) **never escapes `scan()`**:

1. the faulting program's effects for that scan are rolled back — its variables, its function
   block state, its chart state, the global variables and the output image all return to what
   they were when the program started this scan, so its outputs hold their last good state;
2. the program is **halted**: it is skipped on every later scan;
3. the fault appears in `ScanResult.faults` and in `runtime.faults()`;
4. every other program in the list still runs, in order, in the same scan.

`clear_faults()` empties the fault list and restarts every halted program from the state it had
before the faulting scan. This mirrors how a PLC treats a program fault: stop the offending
logic, hold its outputs, keep the rest of the machine scanning, and require an explicit reset.

```python
@dataclass
class PlcFault:
    program: str
    kind: str          # "div_zero" | "math" | "loop" | "internal"
    message: str
    line: int | None; col: int | None; path: str | None
    scan_index: int; sim_time_s: float
```

---

## 8. CompileError and PlcFault

`compile_program` raises `CompileError` and never returns a partly built program.

```python
class CompileError(Exception):
    message: str
    line: int | None        # 1-based, ST
    col: int | None         # 1-based, ST
    path: str | None        # RFC 6901 JSON pointer, LD/SFC
    program: str | None
    errors: list[CompileError]   # always populated; one entry per diagnostic
    def as_dict(self) -> dict    # {"message", "line", "col", "path", "program"}
```

`errors` holds every diagnostic found in one compile — the compiler recovers at statement and
element boundaries and keeps going, so an IDE can mark them all at once. When there is exactly
one diagnostic, `errors == [self]`.

ST diagnostics carry `line`/`col` and render as `program:line:col: message`:

```text
bad:2:5: cannot assign to 'PT3': it is an input tag (direction 'in')
```

LD and SFC diagnostics carry a JSON pointer to the offending field and render as
`program:pointer: message`:

```text
bad_ld:/rungs/0/logic/elements/1/operand: cannot write to 'PT3': it is an input tag (direction 'in')
```

An ST fragment inside a JSON document (an SFC action body or transition condition) carries
**both**, rendering as `program:pointer:line:col: message`, where line and column are relative to
the fragment.

The engine raises exactly four kinds of exception, and they do not overlap:

| Exception | Raised by | Means |
|---|---|---|
| `CompileError` | `compile_program`, `compile_file` | the program is not valid |
| `PlcStateError` | `start_sfc` | the runtime's state forbids the operation (an abort is latched) |
| `ValueError` | `write_inputs`, `force`, `start_sfc`, `write_globals`, `PlcRuntime(...)` | a bad argument: unknown tag, wrong direction, unknown program, conflicting globals |
| `PlcFault` | *not raised* — reported in `ScanResult.faults` and `runtime.faults()` | a program failed during a scan (§7.5) |
