# CIPHLET — Architecture and Capability Design

## Architectural goal
Build Ciphlet as a modular, learning-first AI companion whose physical home is the Raspberry Pi 5.

Separate:
- conversation/orchestration
- voice input/output
- memory
- learning/training
- cybersecurity tools
- browser/computer interaction
- visual workspace
- embodiment
- optional future perception
- external/online lab access

## Learning-first orchestration
Natural requests such as "Teach me Nmap," "Prepare me for SOC work," "Teach me this chapter," "Give me a lab," "Quiz me on yesterday," or "Help me investigate this alert" should be converted into an appropriate lesson, tool, environment, difficulty, and presentation format.

## Memory architecture
Support conversational continuity, semantic retrieval, long-term learning memory, project memory, and temporary working context.

Default behavior retains meaningful learning and project history. Completed projects remain retrievable unless deleted.

Explicit no-memory mode prevents promotion into long-term memory.

User controls review and deletion.

Large raw artifacts should not automatically become permanent semantic memory; useful summaries and learning facts may remain while artifacts stay in appropriate project/file storage.

## Training engine
Support:
- curricula and roadmaps
- user-selected lessons
- adaptive difficulty
- guided exercises
- questions and hints
- expected outcomes
- quizzes
- flashcards
- repetition/review
- mistake analysis
- learning summaries
- practical labs
- post-lab review
- user-material ingestion
- generated learning artifacts

## Cybersecurity capability layer
Support real authorized tools for:
- Linux/networking
- Nmap/network discovery
- traceroute/DNS/network diagnostics
- packet capture/analysis
- Wireshark/tshark
- log analysis
- scripting
- vulnerability assessment
- detection engineering
- threat hunting
- evidence/forensic analysis
- OSINT/research
- red/blue/purple-team training

Tools should be exposed through bounded interfaces and selected according to task and environment.

## Cyber lab environments
Preferred hierarchy:

**local lightweight tool → local container/isolation → occasional ARM Linux VM → external computer/VM → online lab**

The Pi may run lightweight local labs and limited ARM Linux virtualization when practical.

Do not make VMware Workstation or VirtualBox on the Pi a core requirement.

Heavy Windows/enterprise multi-VM environments should use external hardware or online platforms.

## Lab Coach Mode
With explicit authorization, Ciphlet can observe the relevant screen, understand the task, track progress, guide without unnecessarily revealing answers, provide commands/next steps, interpret results, ask the learner to explain findings, correct errors, adapt the exercise, and summarize learning.

## Browser and computer interaction
Screen view and screen control are separate permissions.

Screen view enables observation.

Screen control, when explicitly authorized, may enable:
- click
- type
- scroll
- open applications
- browser navigation
- highlighting/annotation
- supported application interaction

Control permission must never be inferred from viewing permission.

## Voice
Requirements:
- hands-free primary mode
- optional push-to-talk fallback
- "Hey Ciphlet" wake phrase
- visible transcription
- spoken response
- shared voice/text context
- voice isolation
- selective attention
- context-preserving barge-in

## Selective attention
Speech detection must not equal intent detection.

Distinguish user-directed speech from media, lessons, television, other speakers, and background conversation.

Naturally remain quiet when not addressed.

## Visual workspace
Support:
- chat/transcript
- terminal
- logs
- charts/graphs
- dashboards
- diagrams
- images
- documents
- network maps
- timelines
- packet/evidence views
- quizzes
- interactive learning content

Embodiment yields space to the workspace.

## Image and visual generation
Support image generation and programmatic visual artifact creation when the required provider/tool is available, including study visuals, cybersecurity diagrams, network illustrations, and visual explanations.

## Optional vision
Vision is modular future functionality. Possible sources include USB webcam, Raspberry Pi camera, compatible display camera, or another explicitly authorized camera.

Camera availability does not imply continuous monitoring.

## External and online learning
Guide browser-based platforms and external labs.

When the Pi cannot host a required environment, explain why and redirect while maintaining lesson context.

## Modular hardware
Permit later additions such as camera, sensors, Arduino-compatible hardware, displays, audio devices, and other peripherals.

## Security boundary
Ciphlet is independent from CIPHER. CIPHER's security architecture must not be silently copied or weakened into Ciphlet. Future integration requires an explicit design decision.

## Implementation-status rule
Architecture describes target design. It is not proof of implementation. Actual status belongs in CIPHLET_CURRENT_STATE.md and must be updated from runtime/evidence.
