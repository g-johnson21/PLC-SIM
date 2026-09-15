(* LOX tank bang-bang pressurisation: PT3 (LOX bang-bang board pressure) -> S1.
   S1 opens below setpoint - deadband, closes above setpoint + deadband and holds
   in between, which is the hysteresis band the operator actually tunes.
   The loop drives S1 only while enabled (decisions.md D17): disabled, it closes S1
   once and then leaves it to the ground controller. *)

PROGRAM bangbang_lox
VAR_GLOBAL
    (* Operator-set at runtime, not constants. These initial values are the ones
       recorded from the stand's last pre-fire configuration (2026-09-11). *)
    setpoint : REAL := 904.0;   (* psi *)
    deadband : REAL := 15.0;    (* psi *)
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
        END_IF;   // no ELSE: inside the band S1 holds its last state
    ELSIF was_enabled THEN
        S1 := FALSE;   (* disabled this scan: close once, then S1 is the GC's *)
    END_IF;
    was_enabled := bb_lox_enable;

END_PROGRAM
