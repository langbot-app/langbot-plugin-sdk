# Event admission integration check

Based on upstream 7ac774f72eadb104ffb2d5b0c2c7850b667f65ed (SDK 0.7.13).
The LANG-16 fix 11b52589 is not present upstream. Reapplied only listener
admission and its tests, preserving sequential subscriber mutation and
prevent-postorder behavior.

Before: 7 failed / 61 passed. After: 68 passed in tests/runtime/plugin/test_manager.py.
These tests do not claim that faulty EventListeners are isolated from subsequent
subscribers: listener dispatch remains serial by contract. Published 0.7.13 does
not contain this task patch. Core integration uses the locally built SDK.

Actual two-plugin integration on the same post-merge Core: published 0.7.13
blocked the healthy control for 3.162 seconds during another Runner's busy loop;
the patched SDK delivered at 0.389 seconds. Control input was sent after 0.3 s.
The patched combination completed 3,232 synthetic inputs over 749.9 seconds
including startup/recovery, with queues empty and no owned processes left.
This is bounded load, not an overnight real-model memory guarantee.
