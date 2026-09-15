(* LOX tank bang-bang pressurisation: PT3 (LOX bang-bang board pressure) -> S1.
   S1 opens below setpoint - deadband, closes above setpoint + deadband and holds
   in between, which is the hysteresis band the operator actually tunes. *)

PROGRAM bangbang_lox
VAR_GLOBAL
    (* Operator-set at runtime, not constants. These initial values are the ones
       recorded from the stand's last pre-fire configuration (2026-09-11). *)
    setpoint : REAL := 904.0;   (* psi *)
    deadband : REAL := 15.0;    (* psi *)
    bb_lox_enable : BOOL := FALSE;
END_VAR

    IF NOT bb_lox_enable THEN
        S1 := FALSE;
    ELSIF PT3 < setpoint - deadband THEN
        S1 := TRUE;
    ELSIF PT3 > setpoint + deadband THEN
        S1 := FALSE;
    END_IF;   // no ELSE: inside the band S1 holds its last state

END_PROGRAM
