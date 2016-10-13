#!/usr/bin/env bash

RCLONE_LOCAL_DIR=$(cat ~/.rclone.conf | grep -A 5 local-crypt | awk '/remote ?= ?local:/ { gsub("local:","",$NF); print $NF }')

usage() {
    echo "$(basename $0) FILE [DEST]"
}

if [[ $# -lt 1 ]]
then
    usage
    exit 2
fi

FILE="$1"
FILE_DECRYPTED=$(basename "$FILE" .bin)
if [[ -n "$2" ]]
then
    DEST="$2"
else
    DEST=.
fi

if [[ ! -f "$FILE" ]]
then
    echo "$FILE: Not a file" >&2
    exit 3
fi

if [[ ! -d "$DEST" ]]
then
    echo "$DEST: Not a directory" >&2
    exit 3
fi

tmpdir="$(mktemp -d)"
trap "rm -rf $tmpdir" EXIT

mkdir -p "$RCLONE_LOCAL_DIR"
cp "$FILE" "$RCLONE_LOCAL_DIR"

rclone mount local-crypt:/ "$tmpdir" &
rclone_pid="$!"
trap "kill $rclone_pid" EXIT

# wait for file
echo -n "Waiting for file to be decrypted..."
while [[ ! -f "${tmpdir}/${FILE_DECRYPTED}" ]]
do
  sleep 2
done
cp "${tmpdir}/${FILE_DECRYPTED}" "$DEST"
echo 'Done!'

