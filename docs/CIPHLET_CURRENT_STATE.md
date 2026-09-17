# CIPHLET — Current State

**State date:** 2026-09-16

## Purpose
This file records implementation reality and separates verified/implemented behavior from approved design and future work.

## Reported Phase 1 implementation
The reported build includes code paths for:
- typed conversation
- push-to-talk input
- optional wake-word path
- faster-whisper transcription
- Claude API response generation
- tutor mode
- Piper speech integration
- SQLite conversation/basic persistent-fact storage
- graceful degradation
- Ciphlet sprite atlas generation
- a 64-frame sprite engine
- basic idle/listening/thinking/speaking/sleep visual states

The reported implementation was syntax-checked and exercised for non-hardware components.

## Hardware validation pending
The following require validation on the actual Pi/hardware:
- microphone input
- speaker output
- actual Piper voice quality
- wake-word performance against the physical microphone
- real audio behavior
- physical thermals
- final display behavior

## Reported not implemented
The reported Phase 1 build explicitly identified these as not done:
- vision
- image generation
- real Sigma/YARA/log-file tooling
- semantic memory
- true barge-in
- interaction with dynamically swapped content panels

## Approved target requirements
These must not be reported as implemented until verified:
- natural hands-free conversation as primary voice mode
- "Hey Ciphlet" wake phrase
- context-preserving barge-in
- selective attention
- voice isolation
- semantic long-term learning memory
- completed-project memory retention
- explicit no-memory conversations
- user-controlled memory review/deletion
- personalized Lab Coach Mode
- local lightweight cybersecurity training environments
- intelligent Pi/external/online lab selection
- authorized red/blue/purple-team tool use
- SOC preparation/training
- image generation
- dashboards, charts, graphs, diagrams
- dynamic terminal/log/evidence workspace
- adaptive embodiment/workspace
- separate screen-view and screen-control permissions
- optional future camera/vision
- modular future hardware

## Repository
A dedicated Ciphlet GitHub repository is an approved requirement. Record repository/commit evidence here only after actual repository creation and verification.

## Status vocabulary
**IMPLEMENTED / VERIFIED** — observed working through actual execution/testing.

**IMPLEMENTED / HARDWARE TEST PENDING** — code exists but physical behavior is not verified.

**APPROVED / DESIGNED — NOT IMPLEMENTED** — owner-approved capability not yet complete.

**FUTURE / OPTIONAL** — intentionally deferred capability.

**NOT PLANNED** — outside current scope.

## Source of truth
Implementation truth comes from the actual Ciphlet repository, running system, tests, and hardware evidence. Design MDs describe intended behavior and must not be converted into implementation claims.
