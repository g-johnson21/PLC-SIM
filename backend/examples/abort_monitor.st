(* Auto-abort thresholds. This program only computes the request bit: the scan loop
   decides whether to call runtime.trigger_abort(). *)

PROGRAM abort_monitor
VAR_GLOBAL
    (* PLACEHOLDER -- set by operator; not calibrated *)
    pt0_abort_threshold : REAL := 0.0;    (* chamber pressure, psi *)
    pt5_abort_threshold : REAL := 0.0;    (* LOX manifold, psi *)
    pt15_abort_threshold : REAL := 0.0;   (* fuel engine manifold, psi *)

    (* Arms the monitor. FALSE until the operator has configured the thresholds
       above: with them at their placeholder 0.0 any positive reading requests an
       abort, so an armed monitor safes the stand within two scans of plc.run. *)
    abort_monitor_enable : BOOL := FALSE;

    auto_abort_request : BOOL := FALSE;
END_VAR

    IF abort_monitor_enable THEN
        auto_abort_request := (PT0 > pt0_abort_threshold)
                           OR (PT5 > pt5_abort_threshold)
                           OR (PT15 > pt15_abort_threshold);
    ELSE
        auto_abort_request := FALSE;   (* disarmed: never leave the bit latched true *)
    END_IF;

END_PROGRAM
