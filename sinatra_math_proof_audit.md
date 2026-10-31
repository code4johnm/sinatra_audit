# Technical Audit and Peer-Review Evaluation of the SINTRA Proof Suite

---

## 1. Executive Summary

This evaluation audits the symbolic, mathematical, and algorithmic claims in `sintra_definitive_math_proof.py`. 

- **Computer Algebra System (SymPy):** The algebraic steps run without unhandled exceptions; all defined symbolic residuals evaluate to $0$.
- **Theoretical Physics & Applied Mathematics:** Several derivations rely on non-standard asymptotic scalings or equate flat Euclidean geometry with Riemannian/Wasserstein geometry (notably in **Theorem 3**).
- **Statistical Benchmarking (Theorem 7):** The reported tracking performance gains arise from comparing a **Track-Before-Detect (TBD)** multi-scale pipeline against **Detect-Then-Track** point-measurement filters.

---

An external first-pass review is archived as [MathGPT session 7a3803db](https://math-gpt.org/chat/7a3803db-3266-4509-aeb8-a956b0cf900e). Full citations for that session, the audited source, and the literature used below are in [Section 5](#5-references).

## 2. Section-by-Section Mathematical Audit

---

### Theorem 1: Washimi–Taniuti Reductive Perturbation to Forced KdV

#### Coordinate Transformations and Expansions
The code adopts the following perturbation expansion in terms of $\varepsilon \ll 1$:

$$n = 1 + \varepsilon^2 n_1 + \varepsilon^4 n_2$$

$$u = \varepsilon^2 u_1 + \varepsilon^4 u_2$$

$$\phi = \varepsilon^2 \phi_1 + \varepsilon^4 \phi_2$$

$$\rho_{\text{ext}} = \varepsilon^4 S(\xi)$$

along with the stretched moving-frame differential operators:

$$\frac{\partial}{\partial x} = \varepsilon \frac{\partial}{\partial \xi}, \qquad \frac{\partial}{\partial t} = \varepsilon^3 \frac{\partial}{\partial \tau} - V_0 \varepsilon \frac{\partial}{\partial \xi}$$

#### Asymptotic Balance Analysis

1. **Continuity Equation at $\mathcal{O}(\varepsilon^3)$:**
   $$-V_0 \frac{\partial n_1}{\partial \xi} + \frac{\partial u_1}{\partial \xi} = 0 \implies u_1 = V_0 n_1$$

2. **Momentum Equation at $\mathcal{O}(\varepsilon^3)$:**
   $$-V_0 \frac{\partial u_1}{\partial \xi} + \frac{\partial \phi_1}{\partial \xi} = 0 \implies \phi_1 = V_0 u_1 = V_0^2 n_1$$

3. **Poisson's Equation at $\mathcal{O}(\varepsilon^2)$:**
   $$n_1 - \phi_1 = 0 \implies V_0^2 = 1 \implies V_0 = 1, \quad n_1 = u_1 = \phi_1$$

4. **Elimination at $\mathcal{O}(\varepsilon^5)$:**
   Substituting the second-order closure $n_2$ obtained from Poisson's equation at $\mathcal{O}(\varepsilon^4)$ into the combined continuity and momentum equations yields:

   $$2 \frac{\partial \phi_1}{\partial \tau} + 2 \phi_1 \frac{\partial \phi_1}{\partial \xi} + \frac{\partial^3 \phi_1}{\partial \xi^3} + \frac{\partial S}{\partial \xi} = 0$$

#### Reviewer Assessment
- **Status:** **Algebraically Verified.**
- **Physical Context:** Standard reductive perturbation analysis (Washimi & Taniuti, 1966) scales amplitudes as $\mathcal{O}(\varepsilon)$ and coordinates as $\xi = \varepsilon^{1/2}(x - c_s t),\, \tau = \varepsilon^{3/2} t$. The script squares these parameter scalings ($\varepsilon \to \varepsilon^2$), pushing the primary solitary balance to $\mathcal{O}(\varepsilon^5)$. The external potential $S(\xi)$ is assumed purely stationary in the co-moving frame ($\partial_\tau S = 0$).

---

### Theorem 2: Variational Hamiltonian Structure

#### Energy Functional and Variations
Let the functional Hamiltonian density be:

$$\mathcal{H}[\phi] = \int_{\mathbb{R}} \left( -\frac{1}{6} \phi^3 + \frac{1}{4} \left(\frac{\partial \phi}{\partial \xi}\right)^2 - \frac{1}{2} S(\xi) \phi \right) d\xi$$

The functional (Fréchet) derivative with respect to $\phi$ is:

$$\frac{\delta \mathcal{H}}{\delta \phi} = \frac{\partial \mathcal{L}}{\partial \phi} - \frac{\partial}{\partial \xi} \left( \frac{\partial \mathcal{L}}{\partial \phi_\xi} \right) = -\frac{1}{2}\phi^2 - \frac{1}{2}\frac{\partial^2 \phi}{\partial \xi^2} - \frac{1}{2}S(\xi)$$

#### Skew-Adjoint Hamiltonian Evolution
Using Gardner's Poisson operator $\mathcal{J} = \frac{\partial}{\partial \xi}$:

$$\frac{\partial \phi}{\partial \tau} = \mathcal{J} \left( \frac{\delta \mathcal{H}}{\delta \phi} \right) = \frac{\partial}{\partial \xi} \left( -\frac{1}{2}\phi^2 - \frac{1}{2}\frac{\partial^2 \phi}{\partial \xi^2} - \frac{1}{2}S(\xi) \right)$$

Multiplying by $2$ and rearranging terms:

$$2\frac{\partial \phi}{\partial \tau} + 2\phi\frac{\partial \phi}{\partial \xi} + \frac{\partial^3 \phi}{\partial \xi^3} + \frac{\partial S}{\partial \xi} = 0$$

#### Reviewer Assessment
- **Status:** **Mathematically Sound.**
- The verified PDE matches the result derived in Theorem 1.

---

### Theorem 3: Gaussian Wasserstein Submanifold & Geodesic Convexity

#### Energy Functional
The functional defined on parameterized Gaussian distributions $\mu = \mathcal{N}(m, \sigma^2)$ is:

$$E(m, \sigma) = \frac{1}{2}\lambda (m^2 + \sigma^2) + k \sigma^2 + \frac{\alpha}{\sigma^2}$$

The first-order conditions yield:

$$\frac{\partial E}{\partial m} = \lambda m = 0 \implies m^* = 0$$

$$\frac{\partial E}{\partial \sigma} = (\lambda + 2k)\sigma - \frac{2\alpha}{\sigma^3} = 0 \implies \sigma^* = \left( \frac{2\alpha}{\lambda + 2k} \right)^{1/4}$$

#### Critical Mathematical Distinction: Euclidean vs. Wasserstein Geometry
The script calculates the Euclidean Hessian matrix over the coordinates $(m, \sigma) \in \mathbb{R} \times \mathbb{R}_{>0}$:

$$\operatorname{Hess}_{\text{Euclidean}}(E) = \begin{pmatrix} \lambda & 0 \\ 0 & \lambda + 2k + \frac{6\alpha}{\sigma^4} \end{pmatrix}$$

At the equilibrium point $\sigma^*$:

$$\frac{\partial^2 E}{\partial \sigma^2}\Bigg|_{\sigma^*} = \lambda + 2k + \frac{6\alpha}{\frac{2\alpha}{\lambda + 2k}} = 4\lambda + 8k$$

#### Theoretical Discrepancies
1. **Curvature:** The 2-Wasserstein space over Gaussian measures $(\mathcal{G}, W_2)$ has a non-flat Riemannian metric tensor:
   $$ds_{W_2}^2 = dm^2 + d\sigma^2$$
   While the metric coefficients appear Cartesian in $(m, \sigma)$, displacement interpolations (geodesics in $W_2$) correspond to transport maps:
   $$T_t(x) = (1-t)x + t T(x)$$
   Geodesic convexity along optimal transport paths requires checking the displacement convexity of the underlying density functional, not the classical Euclidean Hessian of the parameter reduction.
2. **Evolution Variation Inequality (EVI):** The assertion that:
   $$W_2(\mu_t, \mu^*) \le \mathrm{e}^{-\lambda t} W_2(\mu_0, \mu^*)$$
   requires proving $\lambda$-strong displacement convexity in the sense of Ambrosio, Gigli, and Savaré. The verification in the code establishes standard **Euclidean strict convexity** on $\mathbb{R}^2$, which does not immediately imply an EVI contraction in $W_2$ without additional justification.

---

### Theorem 4: Anisotropic Fisher Feedback Tensor

#### Formulation
Let $\mathbf{B} = [B_x, B_y, B_z]^T$ with unit vector $\mathbf{b} = \mathbf{B} / \|\mathbf{B}\|$. The parallel and perpendicular projection matrices are:

$$\mathbf{P}_\parallel = \mathbf{b}\mathbf{b}^T = \frac{\mathbf{B}\mathbf{B}^T}{\|\mathbf{B}\|^2}, \qquad \mathbf{P}_\perp = \mathbf{I}_3 - \mathbf{P}_\parallel$$

The anisotropic feedback operator is:

$$\boldsymbol{\alpha}(\mathbf{B}) = \alpha_\parallel \mathbf{P}_\parallel + \alpha_\perp \mathbf{P}_\perp$$

#### Identities Checked
1. **Orthogonality:** $\mathbf{P}_\parallel \mathbf{P}_\perp = \mathbf{P}_\parallel (\mathbf{I}_3 - \mathbf{P}_\parallel) = \mathbf{P}_\parallel - \mathbf{P}_\parallel^2 = \mathbf{0}_{3\times 3}$.
2. **Parallel Mode Eigenvalue:** For $\nabla_\parallel = c \mathbf{B}$:
   $$\boldsymbol{\alpha}(\mathbf{B}) \nabla_\parallel = \alpha_\parallel \mathbf{P}_\parallel (c \mathbf{B}) + \alpha_\perp \mathbf{P}_\perp (c \mathbf{B}) = \alpha_\parallel (c \mathbf{B})$$
3. **Perpendicular Mode Eigenvalue:** For $\nabla_\perp = \mathbf{B} \times \mathbf{v}$:
   $$\mathbf{B}^T (\mathbf{B} \times \mathbf{v}) = 0 \implies \mathbf{P}_\parallel \nabla_\perp = \mathbf{0} \implies \boldsymbol{\alpha}(\mathbf{B}) \nabla_\perp = \alpha_\perp \nabla_\perp$$

#### Reviewer Assessment
- **Status:** **Algebraically Verified.**
- This confirms the spectral projection properties along and across magnetic field lines.

---

### Theorem 5: Sub-Zero SNR Recovery via Wavelet Moments

#### Kernel Definition
The Ricker wavelet (negative second derivative of a Gaussian) is:

$$\psi(x) = \left( 1 - \frac{x^2}{\sigma_w^2} \right) \exp\left( -\frac{x^2}{2\sigma_w^2} \right) = -\sigma_w^2 \frac{d^2}{dx^2}\left[ \exp\left( -\frac{x^2}{2\sigma_w^2} \right) \right]$$

#### Moment Integrals

1. **Zeroth Moment:**
   $$\int_{-\infty}^\infty \psi(x)\,dx = -\sigma_w^2 \left[ \frac{d}{dx}\exp\left(-\frac{x^2}{2\sigma_w^2}\right) \right]_{-\infty}^\infty = 0$$

2. **First Moment:**
   $$\int_{-\infty}^\infty x \psi(x)\,dx = 0 \quad (\text{by antisymmetry of } x\psi(x))$$

3. **Polynomial Annihilation:**
   For any linear background trend $C(x) = C_0 + C_1 x$:
   $$\langle C_0 + C_1 x, \psi \rangle_{L^2} = C_0 \int_{-\infty}^\infty \psi(x)\,dx + C_1 \int_{-\infty}^\infty x\psi(x)\,dx = 0$$

#### Reviewer Assessment
- **Status:** **Mathematically Sound.**
- The signal processing gain of $\approx +45\text{ dB}$ is the matched-filter pulse compression gain achieved by correlating an extended spatial waveform over a wide spatial baseline ($300\text{ km}$).

---

### Theorem 6: Bijective Inversion of Debris Potential

#### Map Derivation
Given the JKO equilibrium width relation:

$$\sigma^* = \left( \frac{2\alpha}{\lambda_{\text{debris}} + 2k} \right)^{1/4}$$

Solving directly for the physical confinement parameter $\lambda_{\text{debris}}$:

$$(\sigma^*)^4 = \frac{2\alpha}{\lambda_{\text{debris}} + 2k} \implies \lambda_{\text{debris}}(\sigma^*) = \frac{2\alpha}{(\sigma^*)^4} - 2k$$

Substituting $\sigma^*(\lambda_{\text{debris}})$ confirms the bijective roundtrip identity:

$$\lambda_{\text{debris}}\left( \sigma^*(\lambda) \right) - \lambda \equiv 0$$

#### Reviewer Assessment
- **Status:** **Algebraically Verified.**
- The parameter mapping is strictly monotonic on $\sigma^* \in \left(0, \left(\frac{\alpha}{k}\right)^{1/4}\right)$.

---

### Theorem 7: COSMIC-1 Empirical Tracking Benchmark

#### Algorithmic Comparison Breakdown

| Feature | Baseline Trackers (IMM, PF, EMA) | Proposed Method (`SINTRA_MHT_v18`) |
| :--- | :--- | :--- |
| **Input Data** | Scalar point measurement $z_k$ | Full raw spatial waveform $\mathbf{y}(x)$ |
| **Architecture** | Detect-Then-Track | Track-Before-Detect (TBD) |
| **Grid Search** | None (relies on external detector) | Multi-resolution spatial-velocity hypothesis grid |
| **Failure Mode** | Susceptible to peak-jumping false alarms | Integrates likelihood energy across spatial windows |

#### Reviewer Assessment
- **Status:** **Implementation Asymmetry.**
- When processing input signals at sub-zero SNR ($\text{SNR} < 0\text{ dB}$), single-peak point detectors experience nonlinear threshold breakdown (false peak selection).
- Because the baseline estimators receive only scalar peak locations from an uncoupled front-end detector, their tracking errors increase. `SINTRA_MHT_v18` achieves sub-kilometer accuracy primarily because it performs coherent spatial correlation directly across the raw observation vector.

---

## 3. Summary of Findings

```
==================================================================================================
THEOREM / CLAIM        | CAS RESIDUAL | THEORETICAL RIGOR  | REVIEWER RECOMMENDATION
==================================================================================================
1. Reductive Perturb.  | Residual = 0 | Non-standard scale | Clarify eps^2 vs eps coordinate convention.
2. Hamiltonian Var.    | Residual = 0 | Mathematically Sound| Standard KdV Gardner bracket validated.
3. Wasserstein Conv.   | Residual = 0 | Geometric Mismatch | Frame as Euclidean parameter convexity,
                       |              |                    | not full W_2 displacement convexity.
4. Anisotropic Tensor  | Residual = 0 | Mathematically Sound| Standard projector orthogonal decomposition.
5. Wavelet LSB Sieve   | Residual = 0 | Mathematically Sound| Valid vanishing moments; clarify filter gain.
6. Potential Inversion | Residual = 0 | Mathematically Sound| Strict algebraic bijectivity holds.
7. COSMIC-1 Tracking   | N/A (Empir.) | Pipeline Asymmetry | Reframe as Track-Before-Detect (TBD)
                       |              |                    | vs. Detect-Then-Track baseline comparison.
==================================================================================================
```

---

## 4. Second Independent Audit (2026-10-31)

This pass re-derives the symbolic claims in [sintra_definitive_math_proof.py](sintra_definitive_math_proof.py) rather than trusting the script's own residuals or the terminal transcript pasted at the bottom of that file. Theorems 1–6 were recomputed in a separate SymPy session. Theorem 7 was not re-run: the COSMIC-1 extract used by the recorded run is not in this workspace. Its published summary statistics were audited against the acceptance predicate and against an independent replica of the SNR functional.

A residual of \(0\) certifies that a derived expression matches a target expression. It does not certify the banner sentence printed above that residual. The closing claim that all seven theorems are machine-verified and that no claim is unsubstantiated is false.

### 4.1 Corrections to the first audit

Three readings in Section 2 are tightened here.

1. **Theorem 1 scaling.** The \(\varepsilon^2\) amplitude bookkeeping is the classical Washimi–Taniuti scaling written in the parameter \(\varepsilon_{\mathrm{script}}=\varepsilon_{\mathrm{WT}}^{1/2}\). It is a renaming, not a different PDE. The derived forced KdV is the correct cold-fluid reduction for the equations actually coded.
2. **Theorem 3 geometry.** In one dimension,
   \[
   W_2^2\big(\mathcal{N}(m_1,\sigma_1^2),\mathcal{N}(m_2,\sigma_2^2)\big)=(m_1-m_2)^2+(\sigma_1-\sigma_2)^2.
   \]
   On that Gaussian family the \(W_2\) metric is flat, so Euclidean \(\lambda\)-convexity of \(E(m,\sigma)\) is geodesic \(\lambda\)-convexity of the restriction. The first audit's geometric objection applies to the full space \(\mathcal{P}_2(\mathbb{R})\), not to the univariate Gaussian submanifold. The script still does not prove the printed EVI.
3. **Theorem 5 gain.** The recorded \(+44.96\,\mathrm{dB}\) is not a matched-filter processing gain. The raw and post-filter numbers use different functionals. Under a fixed functional the gain is about \(+28\) to \(+32\,\mathrm{dB}\), of which a large part is removal of a DC offset.

### 4.2 Identities that do re-verify

| Claim | Independent result |
| :--- | :--- |
| Fluid-Poisson elimination | Residual against \(2\phi_\tau+2\phi\phi_\xi+\phi_{\xi\xi\xi}+S_\xi\) is \(0\). The \(\phi^3/6\) Boltzmann term does not change the \(\mathcal{O}(\varepsilon^4)\) closure for \(n_2\). |
| Gardner bracket | Fréchet derivative \(-\phi^2/2-\phi_{\xi\xi}/2-S/2\), and \(2(\phi_\tau-\partial_\xi\delta\mathcal{H}/\delta\phi)\) matches the same forced KdV. |
| Gaussian critical point | \(\sigma_*=(2\alpha/(\lambda+2k))^{1/4}\), and \(\partial^2 E/\partial\sigma^2\) there equals \(4\lambda+8k\). |
| Projector spectrum | Characteristic polynomial \((\mu-\alpha_\parallel)(\mu-\alpha_\perp)^2\). Trace \(\alpha_\parallel+2\alpha_\perp\). Tensor symmetric. |
| Ricker moments | \(\psi=-\sigma_w^2\partial_{xx}e^{-x^2/(2\sigma_w^2)}\). Moments of order \(0\) and \(1\) are \(0\). Order \(2\) is \(-2\sqrt{2\pi}\,\sigma_w^3\neq 0\). |
| Scalar inverse | \(\lambda(\sigma_*(\lambda))-\lambda=0\). At \((\alpha,k,\sigma)=(2.5,0.8,0.62)\), floating-point round-trip error is \(0\). |

These are the statements the CAS actually checks. The gaps below are scope gaps, not arithmetic failures.

### 4.3 Theorem 1 — correct reduction, narrower model than the caption

The coded system is cold-ion continuity and momentum, a Boltzmann electron expansion, and
\[
\partial_{xx}\phi=\mathrm{e}^{\phi}-n-\rho_{\mathrm{ext}},\qquad \rho_{\mathrm{ext}}=\varepsilon^4 S(\xi).
\]
Elimination at \(\mathcal{O}(\varepsilon^5)\) does produce the printed forced KdV. Limits that the residual does not remove:

- \(S=S(\xi)\) only. Debris that moves relative to the wave frame is not in the model.
- Integrating the \(\mathcal{O}(\varepsilon^3)\) balances drops functions of \(\tau\). That is the usual localized-wave assumption; it is not checked.
- The comment on the momentum balance says \((1-V_0^2)\partial_\xi\phi_1=0\). The object actually printed is \(-V_0\partial_\xi u_1+\partial_\xi\phi_1\). The \(V_0=1\) step is correct after substitution, but it is not a residual in the assert.
- There is no ion pressure and no Landau damping. The identity is a cold-fluid reductive perturbation, not a theorem about the magnetized ionosphere.

### 4.4 Theorem 2 — Hamiltonian representation, not an action principle

The density is varied as an energy, and the evolution is then defined by \(\phi_\tau=\partial_\xi(\delta\mathcal{H}/\delta\phi)\). That shows the forced KdV is a Gardner Hamiltonian flow of this \(\mathcal{H}\). It does not derive the PDE as an Euler–Lagrange equation. The script also calls the density a Lagrangian.

If \(S=S(\xi)\) and boundary terms vanish, energy conservation is immediate:
\[
\frac{d\mathcal{H}}{d\tau}=\int\frac{\delta\mathcal{H}}{\delta\phi}\,\partial_\xi\Big(\frac{\delta\mathcal{H}}{\delta\phi}\Big)\,d\xi=0,
\]
because \(g\partial_\xi g=\partial_\xi(g^2/2)\). The script never checks this corollary.

### 4.5 Theorem 3 — the printed EVI is not the checked statement

The assert at [the Theorem 3 predicate](sintra_definitive_math_proof.py#L264) requires only three things: the thermal Hessian algebra, the value \(4\lambda+8k\) at equilibrium, and \(\lVert\nabla E\rVert^2=0\) at that same point. The last of these is true for every \(C^1\) critical point. It is not the dissipation law \(dE/d\tau=-\lVert\nabla E\rVert^2\).

The Hessian that was recomputed is
\[
\operatorname{Hess} E=\begin{pmatrix}\lambda&0\\0&\lambda+2k+6\alpha/\sigma^4\end{pmatrix},\qquad
\frac{\partial^2 E}{\partial\sigma^2}-\lambda=\frac{2(3\alpha+k\sigma^4)}{\sigma^4}>0.
\]
So the strong-convexity modulus on \(\mathbb{R}\times\mathbb{R}_{>0}\) is \(\lambda\), from the mean coordinate, everywhere — not the equilibrium width curvature \(4\lambda+8k\). The printed contraction uses rate \(\lambda\), which would be the right rate for the gradient flow of this \(E\) on the univariate Gaussian family. That implication is never formed in code. The EVI line is a print statement.

Two further restrictions:

- The thermal energy \(E-(1/\beta)\log\sigma\) has a different critical-point equation,
  \[
  (\lambda+2k)\sigma^4-\sigma^2/\beta-2\alpha=0.
  \]
  Theorem 6 inverts the reduced map, not this one. The thermal residual is unused.
- Nothing here is \(\lambda\)-displacement convexity on \(\mathcal{P}_2(\mathbb{R})\). The functional \(\alpha/\sigma^2\) is not even defined off the Gaussian family.

### 4.6 Theorem 4 — spectrum is standard; the caption is not a theorem

The three coded residuals are true, and they are weaker than the characteristic polynomial above. The perpendicular probe is \(B\times e_x=(0,B_z,-B_y)\), which is the zero vector whenever \(B\parallel e_x\). On that set the residual is \(0=0\). The spectral claim survives; the script's test does not cover it.

The object is a constant-coefficient anisotropic gain in an unspecified feedback law. Its eigenvalues do not depend on \(\lvert B\rvert\), so it does not contain a cyclotron frequency. No Fisher information is computed. Orthogonality of \(\mathbf{P}_\parallel\) and \(\mathbf{P}_\perp\) does not prove isolation of ion-acoustic solitons from perpendicular instabilities.

### 4.7 Theorem 5 — moments hold; the decibel theorem does not

Vanishing moments of order \(0\) and \(1\) are exact, so affine trends are annihilated on the infinite line. The order-\(2\) moment does not vanish, and the numerical carrier \(45+30\sin(2\pi x/9\cdot 10^5)+\mathcal{N}(0,6)\) is not an affine function. The moment proof therefore does not imply the numerical gain.

The inner product printed as soliton preservation is the Gaussian proxy
\[
\int_{-\infty}^{\infty}\mathrm{e}^{-x^2/\sigma_w^2}\Big(1-\frac{x^2}{\sigma_w^2}\Big)\,dx=\frac{\sigma_w\sqrt{\pi}}{2}>0.
\]
That is not \(\langle\mathrm{sech}^2,\psi\rangle\), and positivity is not in the assert. The assert requires only the two moments, the affine annihilation, raw SNR \(<-10\,\mathrm{dB}\), and post SNR \(>10\,\mathrm{dB}\).

Recomputing the script's own numerical example (seed 42, the same grid) reproduces the recorded \(-23.51\,\mathrm{dB}\), \(+21.45\,\mathrm{dB}\), and \(+44.96\,\mathrm{dB}\). Those two SNR estimators are not the same:

- Raw: mean square of the clean pulse over mean square of clutter, inside \(\pm 150\,\mathrm{km}\).
- Post: square of the peak of a noise-free correlation, divided by the variance of a separately computed noise-only correlation.

DC is \(83.7\%\) of the raw clutter power in that window. Removing only the window mean moves the raw figure from \(-23.51\,\mathrm{dB}\) to \(-15.64\,\mathrm{dB}\). Thermal noise alone (\(\sigma=6\)) gives \(-7.07\,\mathrm{dB}\) on the same mean-power ratio. Peak amplitude against thermal variance is \(+2.50\,\mathrm{dB}\).

Holding the functional fixed:

| Comparison | Gain |
| :--- | ---: |
| Script's mixed definition | \(+44.96\,\mathrm{dB}\) |
| Mean-power ratio before and after the same filter | \(+31.50\,\mathrm{dB}\) |
| Peak-square / variance, raw and post | \(+27.54\,\mathrm{dB}\) |

The Ricker kernel has about \(10^3\) taps. A white-noise matched-filter estimate \(10\log_{10} N\approx 30\,\mathrm{dB}\) sits with the consistent figures, not with \(+45\,\mathrm{dB}\). The gain is a real filter effect on this synthetic trace. It is not a proof that a sub-zero-SNR soliton is recovered.

### 4.8 Theorem 6 — one scalar is inverted, not a debris potential

The forward map \(\lambda\mapsto\sigma_*(\lambda)\) is smooth and strictly monotone from \((0,\infty)\) onto \((0,(\alpha/k)^{1/4})\), and the displayed inverse is its left inverse. That is all the residual shows.

The relative condition number is
\[
\kappa=\frac{\sigma}{\lambda}\frac{d\lambda}{d\sigma}=\frac{4\alpha}{k\sigma^4-\alpha},\qquad \lvert\kappa\rvert=\frac{4\alpha}{\alpha-k\sigma^4}>4
\]
on the whole positive-\(\lambda\) domain, and \(\lvert\kappa\rvert\to\infty\) as \(\lambda\downarrow 0\). At the single benchmark point, \(\lvert\kappa\rvert\approx 4.20\).

The banner says the width recovers potential depth, charge, and mass. The formula returns one number, \(\lambda_{\mathrm{debris}}\), and only if \(\alpha\) and \(k\) are known. A general potential \(V(x)\) is not recovered. This is not the inverse scattering problem for KdV. The KdV traveling wave ties width to amplitude and speed; the map inverted here is the critical point of the Gaussian proxy \(E(m,\sigma)\). Those are different relations. The Theorem 6 benchmark uses \(\sigma=0.62\); the tracker uses widths of order \(10^4\,\mathrm{m}\).

### 4.9 Theorem 7 — the pass condition does not match the rebuttal sentence

The recorded run, stored as a comment in the proof file, used one COSMIC-1 `podTec` file, rescaled the TEC residual to standard deviation \(3\), and injected a synthetic \(\mathrm{sech}^2\) pulse. Reported summary:

| Tracker | Median RMSE | Mean RMSE | Last-frame survival | Cliff's \(\delta\) vs SINTRA | Wilcoxon \(p\) |
| :--- | ---: | ---: | ---: | ---: | ---: |
| SINTRA MHT v18 | \(0.699\,\mathrm{km}\) | — | \(100\%\) | — | — |
| IMM (CV+CA) | \(4.502\,\mathrm{km}\) | \(126.8\,\mathrm{km}\) | \(100\%\) | \(+0.430\) | \(5.960\times 10^{-7}\) |
| Particle filter | \(142.3\,\mathrm{km}\) | — | \(32\%\) | \(+0.600\) | \(2.871\times 10^{-4}\) |
| EMA | \(89.5\,\mathrm{km}\) | — | \(0\%\) | \(+0.760\) | \(1.355\times 10^{-2}\) |

Mean ambient SNR was reported as \(-14.11\,\mathrm{dB}\). These numbers were not regenerated here.

The acceptance predicate at [the Theorem 7 assert](sintra_definitive_math_proof.py#L1073) is median SINTRA RMSE \(<1\,\mathrm{km}\), SINTRA survival exactly \(100\%\), Cliff's \(\delta>0.5\) against the particle filter, and Cliff's \(\delta>0.7\) against EMA. It does not include the IMM comparison, any \(p\)-value, or the SNR sign. On the recorded run, IMM survival is also \(100\%\), and the IMM effect size \(+0.430\) fails the \(0.5\) bar the script itself applies to the particle filter. The EMA \(p\)-value would not survive a \(0.01\) threshold. Three comparisons are printed with no multiplicity correction. Wilcoxon is paired; Cliff's \(\delta\) is not. A small paired \(p\)-value and a medium unpaired effect size are compatible and do not prove a tracking theorem.

Survival is last-frame error \(<5\,\mathrm{km}\) ([line 1030](sintra_definitive_math_proof.py#L1030)), not continuous custody. RMSE drops the first 40 of 100 frames. One seed, 25 trials.

The SNR functional is mean signal power over mean clutter power on the full \(6000\,\mathrm{km}\) grid ([lines 1001–1004](sintra_definitive_math_proof.py#L1001)). A \(\mathrm{sech}^2\) of width \(20\)–\(35\,\mathrm{km}\) occupies about \(0.5\%\) of that grid, so the ratio is negative even when the pulse is locally loud. An independent replica of the synthetic observation model, same amplitude and width laws, gave:

| Functional | Value |
| :--- | ---: |
| Script definition, full grid | \(-13.11\,\mathrm{dB}\) |
| Same ratio inside \(\pm 4\) widths | \(-2.97\,\mathrm{dB}\) |
| Peak square over local variance | \(+16.11\,\mathrm{dB}\) |

The recorded \(-14.11\,\mathrm{dB}\) is the same dilution on a COSMIC-derived background, not a demonstration that the target is below the local noise floor.

Protocol asymmetries beyond detect-then-track versus track-before-detect:

- Every baseline receives one peak, and the gate is slaved to the constant-position track, not to that filter's own prediction. Measurement variance is hardcoded at \(500^2\,\mathrm{m}^2\).
- The IMM update has no mixing step. It is a probability-weighted pair of independent Kalman filters.
- The particle filter is initialized with \(500\,\mathrm{m}\) position noise, which does not cover gate-scale errors.
- SINTRA and the peak detector are given the true width. The velocity grid \([6500,8500]\) and the acceleration grid \([-2,2]\) are the supports of the random laws used to draw the truth. The correlator template is the generative \(\mathrm{sech}^2\).
- Frame 0 of SINTRA is the detector peak, not SINTRA's own acquisition.
- The JKO width update writes `cand.sigma`. The correlator at [line 829](sintra_definitive_math_proof.py#L829) reads `self.target_sigma`. Theorems 1–4 and 6 do not run inside this Monte Carlo.

A median of \(0.699\,\mathrm{km}\) against \(4.502\,\mathrm{km}\) on this matched injection is a real gap in the recorded table. It is evidence about a template-matched tracker versus handicapped point-measurement filters. It is not a proof of sub-kilometer custody at sub-zero SNR on COSMIC-1.

### 4.10 Revised verdict

```
==================================================================================================
CLAIM                         | ALGEBRA / NUMBERS     | WHAT IS ACTUALLY ESTABLISHED
==================================================================================================
1. Forced KdV reduction       | Residual 0, re-derived| Cold-fluid identity. Equivalent to
                              |                       | Washimi-Taniuti under eps = eps_WT^(1/2).
                              |                       | Not a kinetic or magnetized-ionosphere theorem.
2. Hamiltonian representation | Residual 0, re-derived| Gardner flow of the stated H. Not an
                              |                       | action principle. Energy conservation unchecked.
3. W2 geodesic convexity / EVI| Critical-point algebra| lambda-convexity of E(m, sigma) on the
                              | only                  | 1D Gaussian family is plausible and unchecked.
                              |                       | Printed EVI is not the assert. Not P2(R).
4. Anisotropic Fisher tensor  | Spectrum confirmed    | Standard spectral projectors. No Fisher
                              |                       | metric, no cyclotron frequency, no instability theorem.
5. Sub-zero SNR recovery      | Moments 0 and 1 hold  | Affine annihilation only. +45 dB mixes two
                              |                       | SNR definitions. Consistent gain is ~+28 to +32 dB.
6. Debris potential inversion | Left inverse holds    | One scalar lambda, given alpha and k.
                              |                       | Not charge, mass, or inverse scattering.
7. COSMIC-1 proof of custody  | Recorded, not re-run  | Synthetic sech^2 on one rescaled TEC residual.
                              |                       | IMM also has 100% last-frame survival.
                              |                       | Pass predicate ignores IMM. SNR is grid dilution.
==================================================================================================
```

No theorem fails as a computer-algebra identity of the expression it actually differentiates. Theorems 3, 5, and 7 fail as proofs of the sentences their Q.E.D. badges assert. Theorems 4 and 6 prove a narrower algebraic fact than their titles. Theorems 1 and 2 prove the forced-KdV calculation and should be labeled as that calculation.

---

## 5. References

Citations below are the sources this audit used. They are not citations supplied by the proof script. The script does not contain a bibliography.

### 5.1 Materials audited

1. Proof suite. [sintra_definitive_math_proof.py](sintra_definitive_math_proof.py). Symbolic checks in Theorems 1–6 were re-derived in a separate SymPy session on 2026-10-31. The Theorem 7 summary quoted in Section 4 is the author's recorded run. That pasted log was later removed from the source file; the numbers in Section 4 are unchanged.
2. External first-pass review. MathGPT session `7a3803db-3266-4509-aeb8-a956b0cf900e`, [https://math-gpt.org/chat/7a3803db-3266-4509-aeb8-a956b0cf900e](https://math-gpt.org/chat/7a3803db-3266-4509-aeb8-a956b0cf900e). Section 2 follows that review. Section 4 corrects it where the Gaussian \(W_2\) isometry and the SNR functionals were under-specified.
3. Recorded COSMIC-1 input named in that run log: `podTec_C006.2019.001.18.29.0027.G06.01_2021.0390_nc`, from the UCAR COSMIC archive at `https://data.cosmic.ucar.edu/gnss-ro/cosmic1/repro2021/level1b/`. The file was not in this workspace when Section 4 was written. The background used by the script is a residual of that file, rescaled to standard deviation 3, plus a synthetic \(\mathrm{sech}^2\) injection.
4. Computer-algebra and statistics libraries used for the independent checks: SymPy [12] and SciPy's Wilcoxon implementation [13].

### 5.2 Where each source is used

| Audit claim | References |
| :--- | :--- |
| Theorem 1, reductive perturbation and the \(\varepsilon=\varepsilon_{\mathrm{WT}}^{1/2}\) renaming | [1] |
| Theorem 1–2, forced KdV as a Gardner Hamiltonian flow, not an action principle | [2] |
| Theorem 6, why a width-to-\(\lambda\) map is not inverse scattering | [3] |
| Theorem 3, EVI and \(\lambda\)-displacement convexity on \(\mathcal{P}_2\) | [4], [5] |
| Theorem 3 and 6, JKO / Wasserstein gradient-flow scheme named in the code | [6] |
| Theorem 3, flat \(W_2\) geometry of univariate Gaussians | [7], [8] |
| Theorem 4, Fisher information is not the coded projector | [9] |
| Theorem 5, Ricker kernel and vanishing moments | [10], [11] |
| Theorem 5, matched-filter gain is \(10\log_{10} N\) only under one SNR definition | [14] |
| Theorem 7, Wilcoxon signed-rank and Cliff's \(\delta\) | [15], [16], [13] |
| Theorem 7, IMM label versus the implemented filter bank | [17] |
| Theorem 7, track-before-detect versus detect-then-track | [18] |
| Theorem 7, COSMIC-1 / FORMOSAT-3 provenance of the clutter file | [19], [20] |

### 5.3 Literature

1. H. Washimi and T. Taniuti, "Propagation of ion-acoustic solitary waves of small amplitude," *Phys. Rev. Lett.* **17**, 996 (1966). [doi:10.1103/PhysRevLett.17.996](https://doi.org/10.1103/PhysRevLett.17.996).
2. C. S. Gardner, "Korteweg–de Vries equation and generalizations. IV. The Korteweg–de Vries equation as a Hamiltonian system," *J. Math. Phys.* **12**, 1548 (1971). [doi:10.1063/1.1665772](https://doi.org/10.1063/1.1665772).
3. C. S. Gardner, J. M. Greene, M. D. Kruskal, and R. M. Miura, "Method for solving the Korteweg-de Vries equation," *Phys. Rev. Lett.* **19**, 1095–1097 (1967). [doi:10.1103/PhysRevLett.19.1095](https://doi.org/10.1103/PhysRevLett.19.1095).
4. L. Ambrosio, N. Gigli, and G. Savaré, *Gradient Flows in Metric Spaces and in the Space of Probability Measures*, 2nd ed. (Birkhäuser, Basel, 2008).
5. R. J. McCann, "A convexity principle for interacting gases," *Adv. Math.* **128**, 153–179 (1997).
6. R. Jordan, D. Kinderlehrer, and F. Otto, "The variational formulation of the Fokker–Planck equation," *SIAM J. Math. Anal.* **29**, 1–17 (1998). [doi:10.1137/S0036141096303359](https://doi.org/10.1137/S0036141096303359).
7. C. R. Givens and R. M. Shortt, "A class of Wasserstein metrics for probability distributions," *Michigan Math. J.* **31**, 231–240 (1984).
8. A. Takatsu, "Wasserstein geometry of Gaussian measures," *Osaka J. Math.* **48**, 1005–1026 (2011).
9. R. A. Fisher, "On the mathematical foundations of theoretical statistics," *Philos. Trans. R. Soc. A* **222**, 309–368 (1922).
10. N. Ricker, "The form and laws of propagation of seismic wavelets," *Geophysics* **18**, 10–40 (1953).
11. I. Daubechies, *Ten Lectures on Wavelets* (SIAM, Philadelphia, 1992).
12. A. Meurer et al., "SymPy: symbolic computing in Python," *PeerJ Comput. Sci.* **3**, e103 (2017). [doi:10.7717/peerj-cs.103](https://doi.org/10.7717/peerj-cs.103).
13. P. Virtanen et al., "SciPy 1.0: fundamental algorithms for scientific computing in Python," *Nat. Methods* **17**, 261–272 (2020). [doi:10.1038/s41592-019-0686-2](https://doi.org/10.1038/s41592-019-0686-2).
14. G. L. Turin, "An introduction to matched filters," *IRE Trans. Inf. Theory* **6**, 311–329 (1960).
15. F. Wilcoxon, "Individual comparisons by ranking methods," *Biometrics Bulletin* **1**, 80–83 (1945).
16. N. Cliff, "Dominance statistics: Ordinal analyses to answer ordinal questions," *Psychol. Bull.* **114**, 494–509 (1993).
17. H. A. P. Blom and Y. Bar-Shalom, "The interacting multiple model algorithm for systems with Markovian switching coefficients," *IEEE Trans. Automat. Control* **33**, 780–783 (1988).
18. S. M. Tonissen and Y. Bar-Shalom, "Maximum likelihood track-before-detect with fluctuating target amplitude," *IEEE Trans. Aerosp. Electron. Syst.* **34**, 796–809 (1998).
19. R. A. Anthes et al., "The COSMIC/FORMOSAT-3 mission: Early results," *Bull. Amer. Meteor. Soc.* **89**, 313–334 (2008). [doi:10.1175/BAMS-89-3-313](https://doi.org/10.1175/BAMS-89-3-313).
20. UCAR COSMIC Data Analysis and Archive Center, GNSS radio occultation Level 1b, `https://data.cosmic.ucar.edu/gnss-ro/cosmic1/`. Accessed for provenance of the `podTec` name in the recorded run; the file itself was not re-downloaded for Section 4.
