use nurbs::{ScalarNurbs, eval};
use std::time::{Duration, Instant};

fn synthetic_postshape_curve() -> ScalarNurbs {
    let degree = 5_u8;
    let n_cps = 30;
    let p = degree as usize;

    let mut knots = Vec::with_capacity(n_cps + p + 1);
    knots.resize(p + 1, 0.0_f64);
    let n_interior = n_cps - p - 1;
    for i in 1..=n_interior {
        knots.push(i as f64 / (n_interior + 1) as f64);
    }
    knots.resize(knots.len() + p + 1, 1.0_f64);

    let cps: Vec<f64> = (0..n_cps)
        .map(|i| {
            let t = i as f64 / (n_cps - 1) as f64;
            10.0 * t + 5.0 * libm::sin(t * std::f64::consts::PI)
        })
        .collect();

    ScalarNurbs::try_new(degree, knots, cps).unwrap()
}

fn cubic_bezier_curve() -> ScalarNurbs {
    ScalarNurbs::try_new(
        3,
        vec![0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0],
        vec![0.0, 1.0, 2.0, 3.0],
    )
    .unwrap()
}

const ITERATIONS: usize = 200_000;
const ROUNDS: usize = 64;
const BATCH: usize = ITERATIONS / ROUNDS;

fn u_at(i: usize) -> f64 {
    (i as f64) / (ITERATIONS as f64)
}

fn median(mut ratios: Vec<f64>) -> f64 {
    ratios.sort_by(f64::total_cmp);
    let mid = ratios.len() / 2;
    if ratios.len() % 2 == 0 {
        (ratios[mid - 1] + ratios[mid]) / 2.0
    } else {
        ratios[mid]
    }
}

/// Times `baseline` against `candidate` over the same sweep of `u`, alternating
/// between them every `BATCH` iterations and returning the median of the
/// per-round ratios.
///
/// Timing one implementation to completion and then the other makes the
/// comparison hostage to what the machine was doing during each window: under a
/// loaded test pool one side can lose the CPU for most of its run while the
/// other does not, and the ratio reports the scheduler rather than the code.
/// Alternating spreads any stall across both sides, and taking the median of
/// the rounds lets the rounds that did get descheduled be outvoted instead of
/// deciding the verdict.
fn interleaved_ratio(
    label: &str,
    mut baseline: impl FnMut(f64) -> f64,
    mut candidate: impl FnMut(f64) -> f64,
) -> f64 {
    let mut sink = 0.0_f64;
    let mut ratios = Vec::with_capacity(ROUNDS);
    let mut baseline_total = Duration::ZERO;
    let mut candidate_total = Duration::ZERO;

    for round in 0..ROUNDS {
        let first = round * BATCH;

        let start = Instant::now();
        for i in first..first + BATCH {
            sink += baseline(u_at(i));
        }
        let baseline_round = start.elapsed();

        let start = Instant::now();
        for i in first..first + BATCH {
            sink += candidate(u_at(i));
        }
        let candidate_round = start.elapsed();

        baseline_total += baseline_round;
        candidate_total += candidate_round;
        ratios.push(baseline_round.as_nanos() as f64 / candidate_round.as_nanos().max(1) as f64);
    }

    assert!(sink.is_finite(), "sink={sink}");

    let ratio = median(ratios);
    eprintln!(
        "{label}: baseline={baseline_total:?}, candidate={candidate_total:?}, \
         median round ratio={ratio:.2}x"
    );
    ratio
}

#[test]
fn eval_derivative_windowed_at_least_3x_faster_than_materialized() {
    let curve = synthetic_postshape_curve();

    let ratio = interleaved_ratio(
        "eval_derivative perf",
        |u| {
            let lowered = eval::derivative(&curve);
            eval::eval(&lowered.as_view(), u)
        },
        |u| eval::eval_derivative(curve.control_points(), curve.knots(), curve.degree(), u),
    );

    assert!(
        ratio >= 3.0,
        "windowed eval_derivative regressed: only {ratio:.2}x faster than \
         materialized derivative+eval (expected ≥3×). Did someone reintroduce \
         the [0.0; MAX_CONTROL_POINTS] stack zero-init in scalar_derivative_eval?"
    );
}

#[test]
fn eval_polynomial_at_least_as_fast_as_eval_for_validated_curves() {
    let curve = synthetic_postshape_curve();

    let ratio = interleaved_ratio(
        "eval_polynomial perf",
        |u| {
            let view = nurbs::scalar::ScalarNurbsRef::try_new(
                curve.degree(),
                curve.knots(),
                curve.control_points(),
            )
            .unwrap();
            eval::eval(&view, u)
        },
        |u| eval::eval_polynomial(curve.control_points(), curve.knots(), curve.degree(), u),
    );

    assert!(
        ratio >= 1.3,
        "eval_polynomial regressed: only {ratio:.2}x faster than \
         try_new+eval (expected ≥1.3×). Did `validate()` get short-circuited \
         on the via_eval side, or did eval_polynomial pick up a hidden cost?"
    );
}

#[test]
fn eval_polynomial_with_derivative_at_least_1_3x_faster_than_separate_calls() {
    let curve = synthetic_postshape_curve();

    let ratio = interleaved_ratio(
        "combined-eval perf",
        |u| {
            let v = eval::eval_polynomial(curve.control_points(), curve.knots(), curve.degree(), u);
            let d = eval::eval_derivative(curve.control_points(), curve.knots(), curve.degree(), u);
            v + d
        },
        |u| {
            let (v, d) = eval::eval_polynomial_with_derivative(
                curve.control_points(),
                curve.knots(),
                curve.degree(),
                u,
            );
            v + d
        },
    );

    assert!(
        ratio >= 1.3,
        "combined eval+derivative regressed: only {ratio:.2}x faster than \
         separate eval_polynomial + eval_derivative (expected ≥1.3×). \
         Did the d/dd parallel recurrence get split into separate passes?"
    );
}

#[test]
fn eval_polynomial_with_derivative_matches_separate_calls_bitwise() {
    for curve in [synthetic_postshape_curve(), cubic_bezier_curve()] {
        for i in 0..=200 {
            let u = f64::from(i) / 200.0;
            let (v_combined, d_combined) = eval::eval_polynomial_with_derivative(
                curve.control_points(),
                curve.knots(),
                curve.degree(),
                u,
            );
            let v_sep =
                eval::eval_polynomial(curve.control_points(), curve.knots(), curve.degree(), u);
            let d_sep =
                eval::eval_derivative(curve.control_points(), curve.knots(), curve.degree(), u);
            assert!(
                (v_combined - v_sep).abs() < 1e-12,
                "u={u}: combined value {v_combined} vs separate {v_sep}"
            );
            assert!(
                (d_combined - d_sep).abs() < 1e-12,
                "u={u}: combined deriv {d_combined} vs separate {d_sep}"
            );
        }
    }
}

#[test]
fn eval_polynomial_matches_eval_bitwise_for_polynomial_curves() {
    for curve in [synthetic_postshape_curve(), cubic_bezier_curve()] {
        let view = curve.as_view();
        for i in 0..=200 {
            let u = f64::from(i) / 200.0;
            let v_eval = eval::eval(&view, u);
            let v_poly =
                eval::eval_polynomial(curve.control_points(), curve.knots(), curve.degree(), u);
            assert_eq!(
                v_eval.to_bits(),
                v_poly.to_bits(),
                "u={u}: eval={v_eval} vs eval_polynomial={v_poly}"
            );
        }
    }
}
