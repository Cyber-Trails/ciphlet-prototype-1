# CIPHLET — FINAL ARCHITECTURE & PRODUCT DEFINITION
## Pre-Engineering Baseline
**Date:** 2026-09-16  
**Status:** Design baseline for review and handoff to Claude Code  
**Project:** CIPHLET — Cybersecurity Intelligent Personal Helper for Learning, Exploration & Training  
**Pronunciation:** SIGH-flit / SIF-let

---

# 1. PRODUCT DEFINITION

Ciphlet is a **voice-first, embodied AI cybersecurity mentor and learning companion living on a Raspberry Pi 5**.

Ciphlet is not primarily a generic desktop assistant. Its central purpose is to help the user **learn, practice, understand, remember, and apply cybersecurity and technical knowledge**.

Its primary roles are:

- learning facilitator
- teacher
- mentor
- learning buddy
- cybersecurity training companion
- general technical companion

The intended interaction loop is:

**User intent → Ciphlet understands → plans the learning/task experience → selects the appropriate execution environment → guides the user → observes results when authorized → explains and adapts → records useful learning history → recalls it later.**

Desktop, browser, screen, tool, and workspace capabilities exist primarily to support this learning/mentoring role.

The Pi 5 is Ciphlet's **physical home and local orchestration/interface**, not necessarily the machine that must perform every computationally heavy task.

---

# 2. PRODUCT PRINCIPLES

## 2.1 Teacher first

Ciphlet should teach rather than merely provide answers.

Tutor behavior should:

- encourage the user to think
- ask useful questions
- give hints
- wait for attempts
- explain why an answer is correct or incorrect
- adapt difficulty
- recognize confusion
- re-explain concepts
- connect new material to prior learning
- use repetition and review

## 2.2 Learning is central, not an add-on

Ciphlet should eventually support:

- lessons
- guided labs
- cybersecurity scenarios
- quizzes
- flashcards
- practice tests
- study guides
- roadmaps
- visual explanations
- diagrams
- charts
- dashboards
- images
- practical exercises
- spaced repetition
- review of previous learning

## 2.3 Hardware realism

The architecture must respect Raspberry Pi 5 resource limits.

When a task is too heavy, incompatible, or otherwise inappropriate for the Pi, Ciphlet should intelligently use or recommend an appropriate alternative while preserving the user's learning context.

## 2.4 Reuse first

Prefer mature, maintained, reliable components over unnecessary custom reinvention.

Keep Ciphlet-specific orchestration, learning behavior, memory policy, permissions, and product identity separate from replaceable implementation components.

## 2.5 Incremental implementation

The architecture should support the complete intended product, while implementation proceeds incrementally according to dependencies, hardware validation, resource limits, and engineering evidence.

A feature being planned does not mean it is implemented.

---

# 3. PERSONALITY

Ciphlet's baseline personality is:

- youthful
- curious
- playful
- clever
- warm
- energetic
- slightly mischievous
- naturally humorous

During:

- teaching
- troubleshooting
- investigations
- warnings
- difficult technical work

Ciphlet becomes calmer, clearer, and more focused.

Avoid:

- babyish behavior
- squeaky behavior
- hyperactivity
- obnoxious behavior
- excessive theatricality

The personality should remain compatible with a serious cybersecurity learning environment.

---

# 4. VOICE AND CONVERSATION

## 4.1 Primary interaction

**Hands-free voice is Ciphlet's intended primary interaction model.**

Push-to-talk is a **fallback/recovery mechanism**, not the primary interaction model.

Intended wake phrase:

> **Hey Ciphlet**

## 4.2 Shared conversation

Voice and typed interaction must use the **same conversation context**.

Ciphlet is one assistant, not separate voice and chat assistants.

The user should be able to:

- speak
- type
- switch between speaking and typing
- see speech transcribed
- receive readable responses
- receive spoken responses

without losing conversational context.

## 4.3 Required voice behavior

The intended system includes:

- wake word
- selective attention
- natural standby behavior
- voice isolation
- true barge-in
- context-preserving interruption handling
- continuous natural conversation

## 4.4 Selective attention

Ciphlet should not constantly react to environmental speech.

Examples of background material that should not automatically activate Ciphlet:

- movies
- television
- other lessons
- other people's conversations
- unrelated environmental speech

The always-listening layer should be lightweight and should determine whether Ciphlet was actually addressed before invoking heavier speech processing.

## 4.5 Voice isolation

Voice isolation should be available as a user-controlled capability.

Example:

> "Ciphlet, voice isolation."

This should improve focus on the user's voice in noisy environments.

Normal listening should remain available when the user wants Ciphlet to hear environmental audio.

## 4.6 True barge-in

If Ciphlet is speaking and the user interrupts:

1. Ciphlet stops speech output immediately.
2. The active TTS playback buffer is halted/flushed.
3. The new speech is captured.
4. The interruption enters the existing conversation state.
5. Ciphlet responds using the preserved context.
6. The interaction must not become a fresh unrelated conversation.

Barge-in is a required product capability even if its implementation is phased because of technical complexity.

---

# 5. MEMORY

Ciphlet should retain meaningful information that improves long-term learning and continuity.

## 5.1 Memory tiers

### Working memory
Current active session context.

### Episodic memory
Conversation/history records.

### Project memory
Structured information about topics, labs, projects, mistakes, outcomes, and learning progress.

### Semantic memory
Meaning-based retrieval of learned concepts and related information.

## 5.2 Retention principle

Important learning information should remain available unless the user explicitly deletes it.

Completing a project does not automatically mean the associated knowledge should be discarded.

The user should be able to ask:

> "Do you remember what I learned about this?"

> "Teach me that again."

> "Help me prepare for an interview using what I learned."

## 5.3 No-memory conversations

The user can explicitly request that a conversation not be retained as long-term memory.

No-memory mode should prevent promotion into long-term memory while still allowing normal in-session conversation.

## 5.4 User control

The eventual memory system should allow the user to:

- inspect stored memory
- delete memory
- delete project memory
- remove associated semantic records/embeddings

SQLite storage must not be described as semantic memory merely because it stores facts.

---

# 6. LEARNING / TRAINING ENGINE

The Learning Engine is a central Ciphlet subsystem.

Conceptual flow:

**Intent → topic/format/difficulty → learning plan → content → guided interaction → optional lab → outcome → memory → future review**

Ciphlet should understand requests such as:

> "Teach me Nmap."

> "Teach me this chapter of my Linux book."

> "Prepare me for SOC work."

> "Give me a cybersecurity lab."

> "Quiz me on what I learned yesterday."

The Learning Engine should use prior learning history to adapt instruction.

---

# 7. PERSONALIZED LAB COACH

Lab Coach is a core learning capability.

It should guide the user through practical work rather than simply doing the work for them.

Conceptual loop:

1. Establish learning objective.
2. Determine the appropriate lab environment.
3. Prepare the learner.
4. Let the learner perform the work.
5. Observe progress when screen-view permission is granted.
6. Compare observed progress with expected milestones.
7. Provide hints.
8. Ask questions.
9. Recognize success/failure.
10. Explain mistakes.
11. Escalate assistance if the learner is stuck.
12. Record useful learning outcomes.

Screen control is not required for the Lab Coach's core observation/tutoring function.

---

# 8. CYBERSECURITY TRAINING SCOPE

Ciphlet should eventually support training in:

- SOC
- Blue Team
- Red Team
- Purple Team
- threat intelligence
- OSINT
- incident response
- DFIR
- networking
- Linux
- packet analysis
- detection engineering
- threat hunting
- vulnerability analysis
- cybersecurity research
- ethical hacking
- scripting
- SIEM
- security monitoring

Training should use authorized environments.

---

# 9. CYBERSECURITY TOOL LAYER

The cybersecurity tool layer should provide bounded execution rather than unrestricted shell access.

Conceptual flow:

**Tool request → authorization → appropriate environment → sandbox/containment where needed → execution → structured output → interpretation → teaching context → result record**

Potential tools include appropriate:

- Nmap
- packet-analysis utilities
- log-analysis utilities
- scripting tools
- security-analysis tools

Tool availability should depend on:

- authorization
- platform compatibility
- resource requirements
- isolation requirements
- learning objective

The architecture should not assume every tool belongs directly on the Pi.

---

# 10. LAB ENVIRONMENT SELECTOR

Ciphlet should use an environment hierarchy:

**Pi-local → container → limited ARM VM → external computer/VM → online lab/cyber range**

The selector should consider:

- CPU/RAM requirements
- ARM/x86 compatibility
- GUI requirements
- workload
- isolation
- availability
- learning objective

If the requested environment is unsuitable, Ciphlet should explain the limitation and move or redirect the activity appropriately while preserving the lesson context.

VMware/VirtualBox should not be a core Pi requirement.

ARM VM use, if supported, should be occasional and resource-conscious.

Heavy environments such as multi-VM SOC ranges or Windows/AD labs should normally use an external machine or online environment.

---

# 11. SCREEN / BROWSER / COMPUTER INTERACTION

Screen viewing and screen control are separate capabilities.

## Screen view

Allows Ciphlet to observe the user's authorized screen.

Example:

> "Ciphlet, screen view granted."

## Screen control

Allows Ciphlet to interact with the authorized computer/screen.

Control must require a separate authorization.

**View permission must never imply control permission.**

Permissions should be independently grantable and revocable.

The eventual system should support tutoring while the user works in:

- browser-based cybersecurity platforms
- TryHackMe-style environments
- Let's Defend-style environments
- terminals
- external VMs
- authorized desktop environments
- learning platforms

Ciphlet should preferentially teach and guide rather than automatically complete the learner's work.

---

# 12. DYNAMIC WORKSPACE

The display is both:

1. Ciphlet's home/embodiment area
2. a functional workspace

The workspace may display:

- chat
- transcripts
- terminal output
- logs
- network diagrams
- timelines
- charts
- dashboards
- images
- documents
- packet information
- quizzes
- lab information
- evidence views
- interactive content

## Adaptive layout

The embodiment should adapt to workspace needs:

**FULL CIPHLET**
→ **CIPHLET + WORKSPACE**
→ **FULL WORKSPACE**

Ciphlet may shrink into a corner or temporarily disappear when functional content requires the available screen.

This applies regardless of display size.

---

# 13. EMBODIMENT

The approved Ciphlet reference image and sprite/action sheet are visual authority.

**Do not redesign Ciphlet.**

The embodiment should preserve:

- sapphire-blue luminous body
- translucent/energy-like appearance
- internal neural structures
- soma/core
- nodes
- neurons
- dendrites
- neural pathways

The body itself remains sapphire.

State colors primarily affect internal illumination rather than recoloring the entire body.

Approved internal state behavior includes:

- white / white-blue — healthy/normal
- yellow/gold — thinking/processing
- cyan/blue-white — teaching/focused intelligence
- green — success/safe confirmation
- orange — caution/attention
- red — warning/danger
- purple/magenta — special analysis state where appropriate

The soma is an encapsulated internal structure. Its state illumination should appear to glow through a semi-translucent enclosure rather than as a flat painted surface.

The embodiment is a presentation layer.

It does not drive intelligence, memory, tool execution, or learning logic.

---

# 14. VISUAL STATE / ALERT FATIGUE

Routine backend events should not cause constant visual state changes.

Only meaningful user-facing states should reach the embodiment state system.

The embodiment may have states such as:

- idle
- attentive/listening
- thinking
- speaking
- teaching
- investigating
- working
- success
- warning
- sleep

Health/error conditions should be handled according to their user-facing importance rather than causing constant color changes.

---

# 15. HARDWARE ARCHITECTURE

The Raspberry Pi 5 is the physical home of Ciphlet.

Relevant hardware includes:

- Raspberry Pi 5
- 8 GB RAM
- NVMe storage
- microSD storage
- cooling
- USB microphone
- external speaker
- USB audio adapter
- HDMI display
- keyboard/mouse
- future peripherals

## Resource principle

The **8 GB RAM constraint is important**.

The 1 TB NVMe provides storage; it does not substitute for RAM.

Ciphlet should avoid assuming that multiple heavy workloads can run simultaneously.

Potentially heavy activities should be scheduled, isolated, or delegated.

Cooling should be validated under sustained workloads before final enclosure decisions.

---

# 15A. JUNEBOX 8-INCH DISPLAY / POSSIBLE CHASSIS

**Status: PURCHASED / HARDWARE VALIDATION PENDING**

A JUNEBOX 8-inch touchscreen unit has been purchased. It is a candidate for Ciphlet's display/chassis, but its role in the architecture is not yet confirmed.

Known reported characteristics (manufacturer specification, not yet independently verified):

- 8-inch display
- 1280×800 IPS panel
- 5-point capacitive touch
- HDMI input
- USB-C touch interface
- 12V DC power input
- 3.5mm audio jack
- built-in dual stereo speakers
- rear active cooling fans
- removable rear panel
- adjustable stand
- VESA mounting
- manufacturer imagery showing Raspberry Pi mounting

The JUNEBOX may potentially become Ciphlet's display/chassis, replacing the previously considered Pironman-centered enclosure concept. **This is not confirmed until physical inspection and fit/thermal validation are complete.** Do not assume the entire Pironman enclosure will be installed inside the JUNEBOX, and do not describe the JUNEBOX as Ciphlet's final chassis until validated.

Required physical validation before this decision is finalized:

- Raspberry Pi 5 physical fit
- 2280 NVMe drive fit
- cooler clearance
- fan behavior/noise under load
- speaker and audio output operation
- mounting point compatibility
- cable routing
- display function
- touch function
- sustained cooling behavior under realistic Ciphlet workloads

---

# 16. VISION / CAMERA

Vision is a modular future capability.

It is not required for Version One.

Future sources may include:

- small webcam
- display camera
- authorized external camera
- other approved visual sensors

The architecture should allow these to be added without redesigning the core orchestrator.

---

# 17. IMAGE GENERATION AND VISUAL LEARNING

Image generation is a planned capability supporting the learning/workspace system.

Ciphlet should eventually be able to create or present:

- educational images
- diagrams
- charts
- graphs
- dashboards
- visual explanations
- flashcards
- study cards
- other interactive learning material

The Learning Engine should be able to request visual content from the Workspace/visual subsystem.

---

# 18. REPOSITORY AND DOCUMENTATION

Ciphlet must have its own dedicated GitHub repository, separate from CIPHER.

The project must maintain a permanent **Reconstruction Manual** describing the actual implemented system.

The Reconstruction Manual should cover:

- architecture
- repository structure
- dependencies
- installation
- configuration
- hardware
- software
- services
- startup
- testing
- troubleshooting
- recovery
- important implementation decisions

Documentation must distinguish actual evidence from planned capability.

Never put:

- passwords
- API keys
- secrets
- recovery credentials

into the repository.

---

# 19. CIPHER PROJECT BOUNDARY

Ciphlet is independent from CIPHER.

Do not automatically import:

- CIPHER persona
- CIPHER memory
- CIPHER runtime identity
- CIPHER governance
- CIPHER architecture
- CIPHER security model

Any reuse must be an explicit project decision.

Ciphlet's own security/privacy architecture (Section 19A) is intentionally lighter than CIPHER/CIPHER3's, and does not weaken Ciphlet's intended learning, memory, research, Internet, cloud-intelligence, voice, cybersecurity-training, or companionship capabilities merely in the name of security.

---

# 19A. LIGHTWEIGHT CIPHLET SECURITY & PRIVACY BOUNDARY

**Status: APPROVED / DESIGNED — NOT IMPLEMENTED**

Ciphlet must **not** reproduce the full heavyweight CIPHER/CIPHER3 security architecture. Ciphlet's security model is intentionally lightweight: it exists to bound dangerous actions and protect genuinely sensitive information, without unnecessarily disabling Ciphlet's intended capabilities.

## Preserved capabilities

Security design must explicitly preserve these normal, legitimate Ciphlet capabilities:

- remembering ordinary owner-approved personal context, such as the user's name and preferences
- Internet browsing and research
- cloud-assisted intelligence
- ordinary learning material
- normal conversation and companionship
- authorized cybersecurity learning and labs

Personal information must not automatically be treated as something Ciphlet can never remember or use. Memory remains user-controlled per Section 5.

## Personal context vs. secrets

Security design must distinguish ordinary personal context (name, preferences, learning history, everyday facts about the user) from actual secrets: passwords, API keys, authentication tokens, private keys, recovery credentials, and similar authentication material. Only the latter category receives special handling; ordinary personal context is not treated as a secret.

## Boundary elements

The lightweight security boundary includes:

- voice is not inherently authorization
- explicit authorization is required for meaningful/high-impact actions
- screen view does not imply screen control (Section 11)
- a bounded cybersecurity Tool Layer (Section 9) rather than unrestricted AI-owned shell access
- web pages, PDFs, logs, screenshots, retrieved content, and other untrusted input are treated as **data**, not as authority or instructions
- a cloud-disclosure/sensitivity decision (Section 20A, "Data sensitivity routing") before transmitting sensitive material
- secrets protection
- memory privacy controls
- secure secrets/configuration handling
- execution containment where appropriate
- meaningful action/evidence logging
- fail-closed behavior for permissions
- reproducible/update integrity

Ordinary, low-risk interaction must not be turned into constant permission prompts. Authorization friction should scale with actual impact/risk, not apply uniformly to every action.

## V1 identity model

The Version One identity assumption is a **personal-device trust model**: Ciphlet trusts whoever is interacting with it on its own hardware. Facial recognition, speaker biometrics, continuous identity verification, and biometric owner authentication are **not** Version One requirements. See Section 19B for the future biometric authentication concept, which is explicitly out of scope for V1.

---

# 19B. OWNER BIOMETRIC AUTHENTICATION / HAND-SCAN EXPERIENCE

**Status: FUTURE REQUIRED FUNCTION — NOT IMPLEMENTED**

This is **not** a Ciphlet Version One blocker and is **not** authorized for implementation now. It is recorded here as a settled future requirement so it is not lost or reinvented, not as current work.

## Future experience

```text
Hand approaches/is placed on or near Ciphlet
        ↓
sapphire/neural hand-scan animation
        ↓
one finger contacts a small biometric sensor
        ↓
real fingerprint verification
        ↓
full visual hand-scan sequence completes
        ↓
OWNER AUTHORIZED
```

The full-hand scan is a **visual experience**; actual authentication may be performed via a single fingerprint. The exact sensor is **not selected**.

## Future architecture

The future architecture should permit an `OwnerAuthenticationProvider` interface, with possible providers such as:

- PIN/passphrase
- `FingerprintProvider`
- future `Palm/OtherProvider`

This section defines an intended future capability only. It must not be treated as a current implementation requirement, and Claude Code must not begin implementing owner biometric authentication without explicit separate authorization.

---

# 19C. SYSTEM HEALTH & DIAGNOSTICS

**Status: FUTURE REQUIRED FUNCTION — NOT IMPLEMENTED**

This is a settled future requirement, not authorized for implementation now. It is recorded here so it is not lost or reinvented.

Ciphlet must eventually be able to inspect and report its own operational health, covering at least:

- brain providers/routing (§20A "Routing")
- internet connectivity
- memory (SQLite store, §5)
- storage
- CPU/RAM/temperature
- microphone
- speaker/audio
- voice components (§20B: wake, VAD, STT, TTS)
- services/processes
- tools (§9)
- other relevant runtime components

Diagnostics must be evidence-based: Ciphlet diagnoses actual failures from real signals (process state, connection results, sensor readings, error logs) rather than guessing or inferring health from documentation or assumption — consistent with the status-discipline principle that implementation and capability must never be inferred merely from documentation (§22).

Each inspected component must be reportable as one of: **healthy**, **degraded**, **unavailable**, or **failed**. This is a distinct, narrower vocabulary than the document-wide implementation-status vocabulary in §22 (which describes whether a *capability* is built) — health status describes whether a *running* component is currently working.

**This capability is a prerequisite for §19D (Self-Upgrade / Self-Modification).** Ciphlet must be able to reliably observe its own state before it is trusted to modify itself or verify the result of a modification.

---

# 19D. OWNER-AUTHORIZED SELF-UPGRADE / SELF-MODIFICATION

**Status: FUTURE REQUIRED FUNCTION — NOT IMPLEMENTED**

This is a settled future requirement, not authorized for implementation now. It is recorded here so it is not lost or reinvented, and it is **not** authorization to begin implementing it.

**Hard dependency: this capability depends on §19C (System Health & Diagnostics) and must not be built before it.** Self-modification requires trustworthy self-observation both to scope a change correctly and to verify its result; without working diagnostics, Ciphlet cannot tell whether a self-modification succeeded, partially succeeded, or broke something.

Intended flow, after an owner requests a new capability or improvement:

1. Inspect the relevant part of Ciphlet's own system (using §19C diagnostics and ordinary code/documentation inspection).
2. Determine the smallest appropriate change.
3. Propose the change to the owner in plain terms.
4. Request explicit owner authorization.
5. Only after approval, use **bounded** code/Terminal access to implement the change.
6. Test and verify the actual result — using §19C diagnostics and/or direct evidence — before claiming success.

For step 5's implementation work, Ciphlet may use its own/local/free coding intelligence, or request a stronger coding resource (such as Claude) when appropriate. This follows the same brain-provider boundary and cost discipline already established for conversation (§20A, brain routing changes): **paid/premium resources must never be invoked automatically without explicit owner approval**, matching the existing rule that a premium cloud provider is opt-in only, never automatic.

This capability must be bounded by, not exempt from, Ciphlet's existing lightweight security boundary (§19A): explicit authorization for meaningful/high-impact actions, execution containment where appropriate, meaningful action/evidence logging, and fail-closed behavior for permissions all apply here. Self-modification is a high-impact action by definition and must never proceed without the owner's explicit, per-change authorization — voice alone is not authorization (§19A).

---

# 20. HIGH-LEVEL ARCHITECTURE

```text
                         ┌──────────────────────────┐
                         │        CIPHLET           │
                         │  Conversation / Intent   │
                         │       Orchestrator       │
                         └────────────┬─────────────┘
                                      │
             ┌────────────────────────┼─────────────────────────┐
             │                        │                         │
             ▼                        ▼                         ▼
      ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
      │  VOICE I/O  │          │   MEMORY    │          │  LEARNING   │
      │ wake / STT  │◄────────►│ working     │◄────────►│   ENGINE    │
      │ TTS / VAD   │          │ episodic    │          │ lessons     │
      │ isolation   │          │ project     │          │ quizzes     │
      │ barge-in    │          │ semantic    │          │ Lab Coach   │
      └─────────────┘          └─────────────┘          └──────┬──────┘
                                                               │
                                                               ▼
                                                     ┌─────────────────┐
                                                     │ LAB ENVIRONMENT │
                                                     │    SELECTOR     │
                                                     └────────┬────────┘
                                                              │
                             ┌────────────────────────────────┼─────────────────────────┐
                             │                                │                         │
                             ▼                                ▼                         ▼
                           Pi /                          Container /                 External /
                         local tools                    ARM VM                      Online lab
                             │                                │                         │
                             └────────────────────────────────┼─────────────────────────┘
                                                              ▼
                                                     ┌─────────────────┐
                                                     │ CYBER TOOL LAYER│
                                                     │ auth / sandbox  │
                                                     │ execute / capture│
                                                     └────────┬────────┘
                                                              │
                                                              ▼
                                                     ┌─────────────────┐
                                                     │    WORKSPACE    │
                                                     │ terminal / logs │
                                                     │ charts / graphs │
                                                     │ diagrams / labs │
                                                     │ visual content  │
                                                     └────────┬────────┘
                                                              │
                                                              ▼
                                                     ┌─────────────────┐
                                                     │   EMBODIMENT    │
                                                     │ sprite / state  │
                                                     │ adaptive layout │
                                                     └─────────────────┘

SCREEN / BROWSER
      │
      ├── independent screen_view authorization
      │        └── observation → Lab Coach
      │
      └── independent screen_control authorization
               └── controlled interaction → execution surface
```

---


# 20A. AI BRAIN / INTELLIGENCE ARCHITECTURE

Ciphlet uses a **hybrid, routed intelligence architecture**.

The Raspberry Pi 5 hosts Ciphlet's local runtime and physical presence. Substantive teaching, cybersecurity reasoning, research, investigation, long-context analysis, and other high-complexity reasoning may use a stronger cloud-hosted model.

The architecture must not equate Ciphlet with any single model provider.

## Primary intelligence model

The intended initial intelligence pattern is:

**cloud-primary intelligence + local Ciphlet runtime**

This is not a cloud-only product. Wake/listening services, conversation/session orchestration, memory infrastructure, permissions, tool mediation, workspace/embodiment, and appropriate speech processing remain Ciphlet-owned runtime functions.

A cloud model may provide the primary high-quality reasoning capability while remaining replaceable.

## Provider abstraction

Ciphlet should expose a stable internal Brain Provider interface rather than binding product logic directly to Claude, OpenAI, or another provider.

Conceptually:

```text
Ciphlet Orchestrator
        |
        v
Brain Provider Interface
   |       |       |
   v       v       v
Claude   OpenAI   Local/Future Provider
```

Provider-specific adapters may handle differences in APIs, tool schemas, streaming, prompt caching, and other provider behavior.

Ciphlet's product behavior, memory policy, learning logic, authorization rules, and tool boundaries must remain outside the provider adapter.

The default cloud provider for the first implementation remains an implementation/product selection to be finalized from quality, latency, cost, privacy, and integration evidence.

## Local intelligence

The architecture should support a **replaceable small local intelligence provider**.

Do not permanently select a local model by design document alone.

Candidate model families, sizes, quantizations, and inference runtimes must be benchmarked on the actual Raspberry Pi 5 with realistic concurrent Ciphlet workloads.

Potential responsibilities include:

- simple local intent/routing
- degraded offline conversation
- privacy-sensitive local-only processing where feasible
- deterministic/simple local responses
- limited offline assistance

A local model is not required to equal the cloud brain's teaching/reasoning quality.

A model merely fitting into 8 GB RAM does not make it operationally appropriate. Benchmarking must consider RAM headroom, CPU load, thermals, first-token latency, generation rate, STT/TTS concurrency, and user-perceived conversational quality.

**Current candidate runtime: Ollama**, run as a persistent local service (not a per-request subprocess) — chosen over an earlier direct `llama-cli` subprocess approach, which was implemented, deployed to the Pi, and proven unusable (repeated invocation-compatibility and per-turn-reload/latency failures). Ollama is still a candidate, not permanently frozen, but it directly satisfies the "no reload per turn" requirement in a way a per-request CLI invocation cannot. **Current candidate model: `gemma2:2b-instruct-q4_0`**, replacing an earlier forced Qwen2.5-3B choice, selected from real-world Pi 5 voice-assistant deployments rather than by design-document reasoning alone — still subject to the same benchmarking requirement above before being treated as final. See docs/THIRD_PARTY_NOTICES.md for the evidence this was drawn from.

## Routing

The intelligence router should distinguish classes such as:

- trivial/local
- normal conversation
- teaching/reasoning
- cybersecurity analysis
- research
- tool-assisted work
- visual/workspace tasks
- privacy-sensitive/local-only tasks

Complex or ambiguous educational/security reasoning should favor the stronger reasoning provider rather than silently sacrificing teaching quality.

V1 may use simple deterministic/rule-based routing while preserving the interface for later local-model routing.

## Offline behavior

Ciphlet should fail visibly and gracefully when cloud intelligence is unavailable.

Offline operation may include:

- access to locally stored learning material
- review of existing notes/flashcards
- basic local conversation where supported
- local deterministic functions
- explanation that cloud-dependent reasoning/research is temporarily unavailable

Ciphlet must not silently pretend that degraded local intelligence has the same capability as its normal primary brain.

## Memory is external to the brain

Ciphlet's long-term memory is not model weights.

Conceptual flow:

```text
User turn
   ↓
Memory retrieval / semantic search
   ↓
Relevant authorized context
   ↓
Brain Provider
   ↓
Reasoned response
```

Memory remains independently inspectable, manageable, and deletable.

Semantic memory technology should be selected independently from the primary reasoning model.

## Tool execution is external to the brain

The reasoning model must not directly become the execution environment.

Conceptual flow:

```text
Brain requests bounded action
        ↓
Authorization / policy
        ↓
Tool Layer
        ↓
Sandbox / selected environment
        ↓
Structured result
        ↓
Brain + Learning Engine
```

This separation applies regardless of whether the active brain is cloud or local.

## Data sensitivity routing

Ciphlet should support a data-sensitivity decision before information is transmitted to an external intelligence provider.

The intended policy architecture distinguishes, at minimum:

- ordinary learning material that may use cloud intelligence
- user-designated private/local-only material
- security/lab evidence requiring an explicit policy decision
- secrets, credentials, authentication tokens, and similar sensitive values that must not be transmitted merely because they appear inside a log, screenshot, command result, or file

Exact policy behavior will be finalized during implementation/security design.

## Candidate implementation technologies

Technologies such as llama.cpp, Ollama, lightweight embedding models, SQLite-compatible vector search, and thin provider-adapter libraries are **implementation candidates**, not frozen architectural requirements.

Heavy agent frameworks should not be adopted automatically. Claude Code should evaluate whether a mature lightweight typed orchestration/provider component materially reduces engineering effort while preserving Ciphlet-owned control flow.

## Brain benchmarking

Before freezing local inference choices, test the actual Pi for:

- model load RAM
- total system RAM under realistic concurrency
- first-token latency
- tokens/second
- CPU utilization
- temperature/throttling
- STT concurrency
- TTS concurrency
- memory retrieval concurrency
- response quality
- stability over sustained use

The result, not an estimate, determines the local-model selection.

---

# 20B. VOICE ARCHITECTURE — FINALIZED DIRECTION

Voice is a core Ciphlet subsystem and must not be reduced to a TTS-library choice.

**The voice architecture direction is finalized.** Hands-free voice remains Ciphlet's intended primary interaction model (Section 4.1, Section 27). PTT is a fallback/recovery mechanism and must not be treated as a completed substitute for a finished hands-free Version One.

**Status: APPROVED / DESIGNED — NOT IMPLEMENTED.** The pipeline shape, required capabilities, and provider interfaces below are settled. Exact component/provider selection, tuning, and final freezing remain pending real Raspberry Pi 5 / audio hardware benchmarking (Section 20A, "Brain benchmarking"; this section).

## Primary pipeline

```text
Mic
  ↓
audio conditioning / denoise
  ↓
VAD
  ↓
wake / attention
  ↓
STT
  ↓
Ciphlet Orchestrator / Brain
  ↓
streaming TTS provider
  ↓
speaker
```

## Interruption (barge-in) path

While Ciphlet is speaking, a parallel interruption path runs concurrently with playback:

```text
Mic / VAD
  ↓
interruption detector
  ↓
stop/cancel active TTS immediately
  ↓
STT
  ↓
continue within the SAME conversation context
```

This path implements the barge-in behavior required in Section 4.6 and must not create a fresh, unrelated conversation.

## Required architectural capabilities

The architecture must support:

- a local, lightweight, always-listening path
- wake phrase "Hey Ciphlet"
- VAD
- selective attention
- protection against indiscriminate activation from TV/background speech
- voice isolation/noise handling
- acoustic echo/self-hearing mitigation where required
- true barge-in
- immediate TTS cancellation
- preservation of conversation context after interruption
- a shared text/voice session (Section 4.2)
- an optional visible transcript
- intelligent standby

## Replaceable provider interfaces

Components remain replaceable behind stable interfaces rather than being bound into one inseparable service:

- `WakeProvider`
- `STTProvider`
- `TTSProvider`
- `AudioProcessor`

## Candidate technologies (not frozen)

Current leading candidates may include openWakeWord, Silero/WebRTC-class VAD, RNNoise-class audio processing, VOSK (STT — replacing an earlier faster-whisper candidate, based on real Pi voice-assistant deployment evidence; see docs/THIRD_PARTY_NOTICES.md), and Piper. These are **candidates**, not permanently frozen providers, and must not be treated as final simply because they already exist or are already in use.

**Piper must not automatically become Ciphlet's permanent final voice merely because it is local.** Final voice/TTS selection must weigh quality, personality, latency, resource use, licensing, cost, and actual Raspberry Pi 5 benchmarking — comparing voice quality, controllability, prosody/expression, latency, Pi performance, offline capability, licensing, operating cost, and long-duration usability.

## Voice identity

The desired Ciphlet voice remains youthful, warm, bright, curious, playful, and endearing without becoming squeaky, childish, hyperactive, or theatrical (Section 3). It must remain comfortable for long lessons and able to become calmer and more focused for teaching, investigations, and warnings.


# 21. ARCHITECTURAL DEPENDENCIES

The Orchestrator is the central coordination layer.

Learning depends on:

- Memory
- Environment Selector
- Tool Layer
- Workspace

Voice depends on the Orchestrator for:

- conversation state
- turn state
- interruption handling
- modality continuity

Embodiment depends on Orchestrator state but does not control the Orchestrator.

Workspace renders task-derived content but does not become the intelligence layer.

Lab Coach uses screen observation when authorized but does not require screen control.

Screen view and screen control remain independent permission systems.

Self-Upgrade / Self-Modification (§19D) depends on:

- System Health & Diagnostics (§19C) — required first; self-modification cannot be trusted to verify its own results without it
- Tool Layer (§9) — bounded code/Terminal access
- Security Boundary (§19A) — authorization, containment, logging, fail-closed permissions
- Brain Provider routing (§20A) — for selecting local/free vs. premium coding intelligence, with premium never invoked automatically

---

# 22. STATUS DISCIPLINE

Every capability must have an explicit status.

## IMPLEMENTED / VERIFIED

Actually implemented and supported by evidence.

## IMPLEMENTED / HARDWARE TEST PENDING

Software exists but physical hardware validation remains outstanding.

## APPROVED / DESIGNED — NOT IMPLEMENTED

The capability is part of the intended architecture but has not been built.

## FUTURE REQUIRED FUNCTION — NOT IMPLEMENTED

The capability is a settled future requirement of the finished product, but is explicitly not a current implementation target and is not authorized for implementation now (example: Section 19B, owner biometric authentication).

## FUTURE / OPTIONAL

The capability is intentionally deferred or modular, and may or may not ultimately be built (example: Section 16, vision/camera).

## NOT PLANNED

The capability is explicitly out of scope and not part of the intended product.

## UNVERIFIED

A claim or characteristic (e.g. purchased-hardware specifications) has been reported but not independently confirmed through inspection, test, or benchmarking (example: Section 15A, JUNEBOX reported specifications).

No planned feature may be described as implemented without evidence, and implementation must never be inferred merely from documentation.

---

# 23. IMPLEMENTATION PHILOSOPHY

The final architecture should be designed for the complete intended Ciphlet product.

Implementation should proceed incrementally.

Do not create a tiny Version One architecture that must later be discarded.

Instead:

**Design the complete system → establish stable interfaces → implement the smallest useful vertical slices → test on real hardware → expand subsystem by subsystem.**

Hardware validation and software learning-engine development do not need to be artificially serialized when they are technically independent.

---

# 24. RECOMMENDED IMPLEMENTATION ORDER

The exact order may be adjusted by Claude Code after inspecting the actual repository, but the dependency model is:

Stages 1–2 may use temporary engineering bring-up mechanisms (including PTT) to make hardware and the conversation loop testable early. This is distinct from, and does not satisfy, the finished Version One hands-free voice requirement defined in Section 25 — see Section 25 for the explicit distinction between engineering bring-up and a finished V1 product requirement.

### Stage 1 — Establish and validate the physical foundation

- Pi setup
- audio input
- audio output
- display
- thermal behavior
- existing software baseline
- current voice path (temporary engineering bring-up; may include PTT during initial hardware verification)

### Stage 2 — Conversation foundation

- unified typed/voice conversation
- session state
- STT
- TTS
- basic wake path (toward hands-free; PTT may remain available as fallback/recovery per Section 4.1)
- embodiment state integration

### Stage 3 — Learning Engine

- tutor mode
- lesson generation
- guided questions
- hints
- quizzes
- learning state
- basic project records

### Stage 4 — Cybersecurity Tool Layer

- bounded interface
- authorization
- safe allowlisted tools
- output capture
- teaching-oriented interpretation

### Stage 5 — Environment Selector

- local execution
- container execution
- external/online handoff model
- context preservation

### Stage 6 — Memory expansion

- project memory
- semantic retrieval
- spaced review
- user memory controls

### Stage 7 — Screen-view + Lab Coach

- authorized observation
- learning-platform tutoring
- lab milestone tracking

### Stage 8 — Advanced voice

- robust wake word
- selective attention
- voice isolation refinement
- true barge-in
- interruption/context testing

### Stage 9 — Workspace expansion

- dashboards
- charts
- diagrams
- image generation
- dynamic panel interaction

### Stage 10 — Screen control / external computer integration

- independently authorized control
- browser interaction
- external VM interaction

### Stage 11 — Future vision/hardware

- camera
- vision
- additional peripherals
- broader ARM VM use

### Stage 12 — System Health & Diagnostics (§19C)

- brain provider/routing health
- connectivity, memory, storage checks
- CPU/RAM/temperature monitoring
- microphone, speaker/audio, voice-component checks
- services/processes and tools health
- evidence-based healthy/degraded/unavailable/failed reporting

### Stage 13 — Owner-Authorized Self-Upgrade / Self-Modification (§19D)

- **Depends on Stage 12 being in place first** — self-modification requires working self-diagnostics to scope and verify changes
- inspect own system in response to an owner request
- propose smallest appropriate change and request explicit authorization
- bounded code/Terminal access, used only after approval
- local/free coding intelligence by default; premium coding resource only on explicit owner approval, never automatic
- test/verify actual result before claiming success

This is a dependency-aware roadmap, not a requirement to complete every stage before beginning useful work elsewhere.

---

# 25. VERSION ONE

Version One should deliver a **real, usable Ciphlet learning companion**, not merely a hardware demo.

The first useful vertical slice should prioritize:

- Pi 5 operation
- natural conversation
- typed + voice shared context
- STT
- TTS
- functioning hands-free voice interaction (wake → listen → respond), per Section 4.1 and Section 20B
- PTT fallback/recovery
- basic wake path where hardware permits
- tutor behavior
- basic learning/lesson capability
- SQLite-based foundational memory
- basic embodiment
- display/workspace foundation

**Engineering bring-up vs. finished V1 requirement:** PTT may be used as a temporary engineering bring-up mechanism during Stage 1–2 hardware and software verification (Section 24), and remains available afterward as the permanent fallback/recovery mechanism (Section 4.1). However, PTT-only operation does not, by itself, satisfy the finished Version One hands-free voice requirement. Version One is not complete with respect to its primary interaction requirement until hands-free wake-word-to-response voice interaction is functional end-to-end on the actual hardware. A PTT-first system must not be declared finished Ciphlet V1 on that basis alone.

The architecture must leave clean interfaces for later:

- semantic memory
- Lab Coach
- cybersecurity tools
- external/online labs
- screen viewing
- true barge-in
- voice isolation
- screen control
- dashboards
- diagrams
- image generation
- vision

---

# 26. WHAT SHOULD NOT BE FORCED INTO VERSION ONE

Do not make Version One depend on:

- VMware on the Pi
- VirtualBox on the Pi
- multi-VM SOC infrastructure
- heavy Windows environments
- full vision
- camera hardware
- advanced semantic retrieval
- unrestricted shell execution
- full desktop control
- complex external-computer automation
- every cybersecurity tool

These remain compatible with the architecture but should be introduced when their dependencies and implementation requirements are ready.

---

# 27. OWNER PRODUCT DECISIONS ALREADY SETTLED

The following are settled requirements:

1. Ciphlet is pronounced **SIGH-flit**.
2. Ciphlet is a learning facilitator, teacher, mentor, and learning buddy first.
3. Cybersecurity training is a core purpose.
4. Hands-free voice is the intended primary interaction.
5. PTT is fallback/recovery.
6. "Hey Ciphlet" is the intended wake phrase.
7. Natural conversational continuity is required.
8. True context-preserving barge-in is required in the intended final experience.
9. Voice isolation is a desired user-controlled capability.
10. Ciphlet should remain quiet when not intentionally addressed.
11. Important learning history should remain until the user deletes it.
12. Explicit no-memory conversations should be supported.
13. Semantic memory is desired.
14. Screen view and screen control must be separately authorized.
15. Lab Coach should teach and guide rather than simply do the learner's work.
16. The Pi 5 is Ciphlet's physical home, not universal compute.
17. Heavy work may move to external computers or online environments.
18. VMware/VirtualBox is not a core Pi requirement.
19. The dynamic workspace may shrink or hide Ciphlet when useful content needs the display.
20. The approved embodiment must not be redesigned.
21. Image generation, charts, graphs, diagrams, dashboards, flashcards, and visual learning content belong in the intended capability architecture.
22. Vision/camera is modular and can be added later.
23. Ciphlet has its own GitHub repository separate from CIPHER.
24. Ciphlet requires a permanent Reconstruction Manual.
25. Ciphlet remains architecturally independent from CIPHER.
26. Ciphlet's security/privacy architecture is a lightweight boundary (Section 19A) bounding dangerous actions and protecting genuine secrets — it is not a reproduction of CIPHER/CIPHER3's heavyweight security architecture.
27. Ordinary owner-approved personal context (e.g. the user's name, preferences) is not automatically excluded from memory; only actual secrets/credentials (passwords, API keys, tokens, private keys, recovery credentials) require special protection.
28. Owner biometric hand-scan authentication (Section 19B) is a Future Required Function. It is not a Version One requirement and is not authorized for implementation now.
29. The JUNEBOX 8-inch display/chassis (Section 15A) is purchased; whether it becomes Ciphlet's final display/chassis is pending physical fit and thermal validation, not yet confirmed.
30. Hands-free voice must be functionally working end-to-end (not merely PTT) before Version One can be considered finished with respect to its primary interaction requirement (Section 25).
31. System Health & Diagnostics (Section 19C) is a settled Future Required Function: evidence-based, healthy/degraded/unavailable/failed reporting across brain routing, connectivity, memory, storage, CPU/RAM/temperature, microphone, speaker/audio, voice components, services/processes, and tools. Not authorized for implementation now.
32. Owner-Authorized Self-Upgrade / Self-Modification (Section 19D) is a settled Future Required Function, and it explicitly depends on Section 19C being in place first — Ciphlet must be able to reliably observe and verify its own state before it is trusted to modify itself. Not authorized for implementation now. Paid/premium resources must never be invoked automatically without explicit owner approval.

---


# 27A. INTELLIGENCE DECISIONS SETTLED AT DESIGN LEVEL

The following intelligence architecture decisions are settled:

1. Ciphlet is hybrid/routed rather than permanently local-only or cloud-only.
2. Initial substantive intelligence may be cloud-primary while Ciphlet's runtime remains local.
3. Ciphlet must remain provider-neutral through a stable internal brain-provider boundary.
4. Claude Code is an engineering tool and does not determine Ciphlet's runtime AI provider.
5. Memory remains external to the reasoning model.
6. Tool execution remains external to the reasoning model.
7. A small local brain is an architectural capability, but its exact model/runtime must be selected through real Pi benchmarking.
8. A local model is not required to act as a peer to the stronger primary reasoning model.
9. Offline/degraded operation must be explicit rather than silently masquerading as full capability.
10. Data sensitivity must be considered before sending user/lab/security material to cloud intelligence.
11. Specific local models, vector stores, inference runtimes, and orchestration libraries remain implementation candidates until evaluated.
12. The voice architecture direction (pipeline, interruption path, required capabilities, replaceable provider interfaces) is finalized (Section 20B). Exact component/provider selection (wake engine, VAD, STT, TTS, audio processing) remains pending real Pi/audio hardware benchmarking, and no candidate — including Piper — is a permanently frozen final choice.


# 28. FINAL PRODUCT VISION

The finished Ciphlet should feel like a **small physical AI learning companion**, not a computer with a chatbot attached to it.

The user should be able to sit down and say:

> "Hey Ciphlet, teach me something."

Ciphlet should understand the user's goal, remember what has already been learned, construct an appropriate lesson, explain concepts conversationally, create useful visual material, open or guide an appropriate lab environment, observe progress when authorized, provide hints, recognize mistakes, explain what happened, and remember the meaningful outcome for later.

For cybersecurity, it should be capable of moving naturally between:

**conversation → explanation → demonstration → tool → lab → observation → coaching → assessment → memory → review.**

The Raspberry Pi 5 provides the physical home, voice/audio interface, display, embodiment, and local orchestration.

When computation exceeds what the Pi should reasonably handle, Ciphlet should intelligently use the appropriate external or online environment instead of pretending the Pi can do everything.

The defining product principle is:

> **Ciphlet is the learner's companion and mentor; the Pi is its home, not its limitation.**

---

# 29. PRE-ENGINEERING HANDOFF RULE

Before Claude Code implements anything:

1. Read this document and all current Ciphlet documentation.
2. Inspect the actual CIPHLET repository/folder.
3. Determine the actual current implementation state from evidence.
4. Compare implementation against this architecture.
5. Identify discrepancies and obsolete assumptions.
6. Propose an implementation plan.
7. Do not silently change owner-approved product requirements.
8. Ask the owner only about genuinely consequential unresolved decisions.
9. Do not claim implementation until verified.
10. Preserve and update the Reconstruction Manual as the system becomes real.

**This document defines the intended product and architecture. The actual repository and test evidence define what is currently implemented.**
