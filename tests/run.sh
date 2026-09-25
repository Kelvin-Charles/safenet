#!/bin/bash
# Run SafeNet's test scripts (each is a plain Python script that exits non-zero on failure).
# Usage: tests/run.sh [test_name ...]     e.g. tests/run.sh test_sites test_payments
cd "$(dirname "$0")/.." || exit 1
names=("$@")
[ ${#names[@]} -eq 0 ] && names=($(cd tests && ls test_*.py | sed 's/\.py$//'))
fail=0
for n in "${names[@]}"; do
    n="${n%.py}"
    state=$(mktemp -d)
    extra=""
    [ "$n" = test_gw_networks ] && extra=tests/fixtures/gwimg
    if python3 -W ignore "tests/$n.py" "$state" $extra >"$state/out" 2>&1; then
        echo "PASS $n"
    else
        echo "FAIL $n"; tail -8 "$state/out" | sed 's/^/    /'; fail=1
    fi
    rm -rf "$state"
done
exit $fail
