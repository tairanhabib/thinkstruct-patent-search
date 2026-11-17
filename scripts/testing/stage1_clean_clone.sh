#!/bin/bash
# Stage 1: follow the README from a fresh clone, a fresh virtual environment and an EMPTY model cache.
# Usage: stage1_clean_clone.sh REPO WORKDIR ZIP [part1|part3|part2 ...]
# Every command is the README's, copied literally, except the two paths the README leaves to the reader
# (the archive, and the proof of concept's data folder, which goes under WORKDIR instead of /tmp).
# Each step is timed with /usr/bin/time -l (wall clock and peak memory); a failure is recorded, not fatal.
REPO=$1; WORK=$2; ZIP=$3; shift 3; PARTS=${*:-part1 part3 part2}
CLONE=$WORK/clone; LOGS=$WORK/logs; SUMMARY=$WORK/summary.tsv
export HF_HOME=$WORK/hf-cache          # empty cache: a reviewer has downloaded nothing yet
mkdir -p "$LOGS" "$HF_HOME"
[ -f "$SUMMARY" ] || printf "step\texit\tseconds\tpeak_rss_mb\tcommand\n" > "$SUMMARY"
n=$(($(wc -l < "$SUMMARY")))

step() {  # step NAME COMMAND...
  local name=$1; shift; n=$((n + 1)); local log=$LOGS/$(printf %02d $n)_$name
  /usr/bin/time -l -o "$log.time" bash -c "$*" > "$log.log" 2>&1; local code=$?
  local secs=$(awk '/ real /{print $1}' "$log.time"); local rss=$(awk '/maximum resident set size/{printf "%.0f", $1/1048576}' "$log.time")
  printf "%s\t%s\t%s\t%s\t%s\n" "$name" "$code" "$secs" "$rss" "$*" >> "$SUMMARY"
  echo "[$name] exit $code, $secs s, peak $rss MB"
}
sizes() { du -sh "$CLONE/.venv" "$HF_HOME"/hub/models--* "$CLONE/index"/* 2>/dev/null > "$LOGS/sizes_$1.txt"; }

for part in $PARTS; do case $part in
part1)
  step clone "git clone -q '$REPO' '$CLONE'"
  cd "$CLONE" || exit 1
  step venv "python3.11 -m venv .venv"
  source .venv/bin/activate
  step pip_install "pip install -r requirements.txt"
  step unzip "mkdir -p data/small && unzip -j '$ZIP' '*.json' -d data/small && ls data/small | wc -l"
  step ingest_small "python cli.py ingest data/small"
  step search_1 "python cli.py search 'wheel hub with integrated pressure sensor' --cpc B60B --top 5"
  step search_2 "python cli.py search 'tire tread that reduces road noise' --keywords 'noise' --from 2024-06-01 --to 2024-12-31 --top 5"
  step search_3 "python cli.py search --title 'pneumatic tire' --cpc B60C11 --top 5"
  step similar "python cli.py similar --doc 20240051333 --claim 1 --top 5"
  step show "python cli.py show --doc 20240051339"
  step search_warm "python cli.py search 'wheel hub with integrated pressure sensor' --cpc B60B --top 5"
  sizes part1_before_benchmark
  cp -R index "$WORK/index_english_only"   # the English index alone, kept for the later stages
  step benchmark "python scripts/benchmark.py"
  step pytest "python -m pytest"
  sizes part1 ;;
part3)
  cd "$CLONE" && source .venv/bin/activate || exit 1
  step make_parallel_set "python scripts/make_parallel_set.py"
  step ingest_parallel "python cli.py ingest data/parallel"
  step evaluate_multilingual "python scripts/evaluate_multilingual.py"
  step p3_search_1 "python cli.py search 'tyre monitor with an energy harvester that charges the sensor' --top 5"
  step p3_search_2 "python cli.py search 'tyre monitor with an energy harvester that charges the sensor' --top 5 --cross-lingual shared"
  step p3_search_3 "python cli.py search 'pressure sensor that reports tire pressure to the driver' --language de --top 3"
  step p3_search_4 "python cli.py search '轮辋上带有压力传感器的车轮' --top 3 --show-original"
  step p3_show "python cli.py show --doc 20240083200-ZH"
  sizes part3 ;;
part2)
  cd "$CLONE" && source .venv/bin/activate || exit 1
  step docker "docker compose up -d --wait"
  step poc_pip "pip install -r poc/requirements.txt"
  step poc_pgserver "python poc/load_and_query.py --pgserver '$WORK/patent-poc-pgdata'"
  sizes part2 ;;
esac; done
echo DONE
