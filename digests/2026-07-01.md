# The Morning Papers — 2026-07-01

*First edition. ~12 papers across 5 sections, selected from arXiv (cs.LG/CL/AI), Hugging Face trending, and lab feeds — filtered to your interests (agents, RL post-training, LLM/small-model architecture, evaluation, interpretability) with world-models/robotics kept for genuinely major work. Every paper links to its arXiv abstract.*

---

## ⭐ Top Picks

1. **Agentic RL is converging on a real problem: credit assignment over long tool-use trajectories.** Three independent papers (ECHO, TRIAGE, QVal) attack the same weakness in GRPO from different angles — this is the clearest signal of the day and worth reading as a set (see *RL Post-Training*).
2. **[ATMem: memory as an execution state, not a log](https://arxiv.org/abs/2606.31612)** — reframes agent memory around *what to do next* rather than *what was seen*, and an 8B model beats a 230B baseline on AndroidWorld. The most novel idea in the agent-memory cluster.
3. **[MOPD: multi-teacher on-policy distillation](https://arxiv.org/abs/2606.30406)** [open-weights] — a clean recipe for fusing several domain RL experts into one model without the "see-saw" of mixed RL. Deployed in Xiaomi's MiMo-V2-Flash; built on Qwen3-30B-A3B.

---

## 🧠 Agent Memory & Architecture

- **[What Memory Do GUI Agents Really Need? (ATMem + STR-GRPO)](https://arxiv.org/abs/2606.31612)** — TL;DR: memory should track each value's *role and status* (pending/ready/used), not just store observations. Novel: an actively-maintained execution state plus an RL method that learns *when* memory helps via memory-on/off rollout contrasts. 8B ATMem-UI hits 76.6% on AndroidWorld, beating UI-TARS-2-230B. Code promised.
- **[ECHO: Selective Turn Memory in Agentic RL](https://arxiv.org/abs/2606.31650)** — TL;DR: keep each past turn *source-addressable* so outcome rewards can be routed back to the evidence that earned them. Novel: unifies context pruning (for acting) and credit routing (for learning) through one source-indexed trace. 43.4% vs GRPO's 28.9% on BrowseComp-Plus, with fewer turns. (Baidu; Qwen3-32B backbone.)
- **[Managing Procedural Memory in LLM Agents (AFTER benchmark)](https://arxiv.org/abs/2606.23127)** — TL;DR: separates *specialization* from *generalization* in reusable agent skills across 382 enterprise tasks, 6 roles, 22 skills. Finding: skills evolved from diverse multi-model traces transfer best (73.1% cross-model); narrow experience over-specializes. Relevant to how skill/memory layers actually generalize.

## 🔁 RL Post-Training (Credit Assignment Special)

- **[TRIAGE: Role-Typed Credit Assignment](https://arxiv.org/abs/2606.32017)** — TL;DR: adds a *semantic role* axis (decisive / exploration / no-progress / regression) on top of GRPO's outcome credit, with a theoretical result that role-conditioned credit is the MSE-optimal correction from role labels alone. Fixes two GRPO blind spots: punished exploration in failures, rewarded regressions in successes. (LinkedIn/Harvard/JHU.)
- **[QVal: Cheaply Evaluating Dense Supervision Signals](https://arxiv.org/abs/2606.32034)** [open-weights eval] — TL;DR: a *training-free* testbed that scores how well a dense-supervision signal orders actions by reference Q-values — so you can compare methods before any RL run. Sobering finding: simple prompting baselines beat most recent dense-supervision methods; 21 methods × 4 envs × 6 open backbones.
- **[MOPD: Multi-Teacher On-Policy Distillation](https://arxiv.org/abs/2606.30406)** [open-weights] — TL;DR: train per-domain RL experts in parallel, then distill them into one student on *its own* rollouts (dense, on-policy, no exposure bias). +5.5 pts over Mix-RL on Qwen3-30B-A3B; shipped in MiMo-V2-Flash.
- **[DOPD: Dual On-Policy Distillation](https://arxiv.org/abs/2606.30626)** — TL;DR: names a real failure mode — "privilege illusion," where a teacher's edge comes from privileged inputs the student can never replicate — and routes token-level supervision between teacher and self to avoid distilling it. +6–7.5 pts over vanilla OPD across LLM and VLM.

## 🏗️ Model Architecture & Small Models

- **[Multi-Block Diffusion Language Models (MBD-LMs)](https://arxiv.org/abs/2606.29215)** [open-weights] — TL;DR: decodes several blocks concurrently for inter-block parallelism in diffusion LMs, with a Block Buffer that keeps shapes static for CUDA graphs. On LLaDA2-Mini: tokens-per-forward 3.47→6.19 *and* accuracy up slightly. A genuine architecture/inference advance, not a tuning tweak. (SJTU/Huawei.)
- **[Little Brains, Big Feats: Compact LMs for On-Device RAG](https://arxiv.org/abs/2606.30062)** — TL;DR: systematic study showing SLMs can run the *generation* stage of RAG on CPU-only devices within reasonable latency. More survey-than-breakthrough, but a useful data point for the small-but-capable thread. Code + benchmark released.

## 🔬 Interpretability, Safety & Evaluation

- **[Introspective Coupling: Self-Explanation Tracks Behavioral Change](https://arxiv.org/abs/2606.32038)** — TL;DR: models trained (with regularization) to explain an *earlier* checkpoint's behavior end up explaining their *own current* behavior more faithfully — and explanations track behavioral drift without new labels. Novel "Self > Orig" effect with a mechanistic fingerprint; robust across sycophancy and refusal. (MIT; Andreas/Li.)
- **[RL with Metacognitive Feedback (RLMF)](https://arxiv.org/abs/2606.32032)** — TL;DR: reward the model for accurately *judging its own performance*, using self-judgment quality to scale RL advantages. Up to +63% over standard RL on faithful uncertainty calibration while preserving accuracy. First use of metacognitive feedback as an RL signal. (Yale/Google Research; code released.)

## 🌍 World Models & Embodied (Major Work Only)

- **[Orca: A General World Foundation Model](https://arxiv.org/abs/2606.30534)** — TL;DR: BAAI's bet on *Next-State-Prediction* as a unifying objective — one frozen world latent read out to text, images, and robot actions. Trained on 125K hrs of video + 160M events; a frozen Orca-4B beats π0.5 on some real-robot OOD manipulation. Ambitious and worth watching even if early. (Beijing Academy of AI.)

---

*Housekeeping: this is calibration week. Reply with "found [id] useful" or "[id] was a minor tweak, filter harder" and I'll tune selection. Sources, section counts, and the novelty bar are all adjustable on request.*
