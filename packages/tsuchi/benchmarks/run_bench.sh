#!/usr/bin/env bash
# Benchmark runner for Tsuchi AOT compiler
# Compiles each .js benchmark, runs 5 times (median), compares with Python3

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BENCH_DIR="$SCRIPT_DIR"
BUILD_DIR="$BENCH_DIR/build"
RUNS=5

mkdir -p "$BUILD_DIR"

# --- helpers ---

median() {
  # Read numbers from stdin, print the median
  sort -n | awk '{a[NR]=$1} END {print a[int((NR+1)/2)]}'
}

run_n_times() {
  local cmd="$1"
  local times="$2"
  local results=()
  for ((i=1; i<=times; i++)); do
    # Use bash time built-in, capture real time in seconds
    local t
    t=$( { time eval "$cmd" > /dev/null 2>&1; } 2>&1 | grep real | awk '{print $2}' )
    # Convert NmS.SSs format to seconds
    local mins secs
    mins=$(echo "$t" | sed 's/m.*//')
    secs=$(echo "$t" | sed 's/.*m//' | sed 's/s$//')
    local total
    total=$(echo "$mins * 60 + $secs" | bc -l)
    results+=("$total")
  done
  printf '%s\n' "${results[@]}" | median
}

# --- compile benchmarks ---

echo "=== Compiling benchmarks ==="
BENCHMARKS=("fib" "sum_loop" "array_sum" "string_concat" "sieve")

for bench in "${BENCHMARKS[@]}"; do
  js_file="$BENCH_DIR/bench_${bench}.js"
  echo "  Compiling $js_file ..."
  (cd "$PROJECT_ROOT" && uv run tsuchi compile "$js_file" -o "$BUILD_DIR") 2>&1 | tail -1
done

echo ""
echo "=== Running benchmarks (${RUNS} runs each, median) ==="
echo ""

# Print table header
printf "%-20s %12s %12s %10s\n" "Benchmark" "Tsuchi (s)" "Python (s)" "Speedup"
printf "%-20s %12s %12s %10s\n" "--------------------" "------------" "------------" "----------"

for bench in "${BENCHMARKS[@]}"; do
  binary="$BUILD_DIR/bench_${bench}"
  py_file="$BENCH_DIR/bench_${bench}.py"

  # Run Tsuchi binary
  tsuchi_time=$(run_n_times "$binary" "$RUNS")

  # Run Python
  python_time=$(run_n_times "python3 $py_file" "$RUNS")

  # Calculate speedup (Python / Tsuchi). If Tsuchi is slower, show as fraction.
  faster=$(echo "$python_time > $tsuchi_time" | bc -l)
  if [ "$faster" = "1" ]; then
    speedup=$(echo "scale=1; $python_time / $tsuchi_time" | bc -l 2>/dev/null || echo "N/A")
    printf "%-20s %12.3f %12.3f %9.1fx\n" "$bench" "$tsuchi_time" "$python_time" "$speedup"
  else
    slowdown=$(echo "scale=1; $tsuchi_time / $python_time" | bc -l 2>/dev/null || echo "N/A")
    printf "%-20s %12.3f %12.3f  1/%-.1fx\n" "$bench" "$tsuchi_time" "$python_time" "$slowdown"
  fi
done

echo ""
echo "Done."
