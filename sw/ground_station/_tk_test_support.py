"""Dispose test-owned Tcl objects on their creating thread, before worker GC.

Destroying a Tk window alone leaves Python Variable/trace/application cycles.
The next backend test can trigger cyclic GC on its worker and free a Tcl
interpreter there. Keep interpreter teardown and cycle collection on main.
"""
import gc
import threading
import tkinter as tk


def dispose_tk_test(case):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Tk tests must clean up on the main thread')
    # Offline file readers capture their view/test through the injected decoder.
    # They must finish before its final Tcl references are released.
    for thread in threading.enumerate():
        if thread.name in ('rf-iq-file-decode', 'rf-report-file-read'):
            thread.join(3)
            if thread.is_alive():
                raise RuntimeError('Offline UI file worker did not finish')
    root = getattr(case, 'root', None)
    attributes = ('root', 'app', 'monitor', 'window', 'session', 'sender', 'receiver', 'control', 'controller')
    pending = [getattr(case, name, None) for name in attributes]
    seen, variables = set(), []
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, tk.Variable):
            variables.append(value)
        elif isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, (tuple, list, set)):
            pending.extend(value)
        elif isinstance(value, tk.Misc) or type(value).__module__.startswith('sw.ground_station'):
            pending.extend(vars(value).values())
    value = None
    for variable in variables:
        try:
            for modes, command in variable.trace_info():
                variable.trace_remove(modes, command)
        except tk.TclError:
            pass  # Some close-path tests have already destroyed this root.
    variable = None
    if isinstance(root, tk.Misc):
        try:
            for callback in root.tk.call('after', 'info'):
                root.after_cancel(callback)
            root.destroy()
        except tk.TclError:
            pass
    for name in attributes:
        if hasattr(case, name):
            setattr(case, name, None)
    variables.clear()
    # Keep `root` alive locally until collection is finished, then its final
    # reference is released when this main-thread helper returns.
    gc.collect()
