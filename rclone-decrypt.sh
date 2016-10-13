#!/usr/bin/env bash

usage() {
    echo "$(basename $0) [REMOTE] FILE [DEST]"
}

get_config_block() {
    local remote="$1"
    awk '/^\['"${remote}"'\]/ {printline = 1; print; next} /^\[/ {printline = 0}; printline' "$RCLONE_CONFIG"
}

get_config_option() {
    local remote="$1"
    local option="$2"

    local block=$(get_config_block "$remote")
    awk '/'"$option"' ?= ?/ { print $NF }' <<< "$block"
}

get_password() {
    get_config_option "$1" password
}

get_password2() {
    get_config_option "$1" password2
}

gen_config() {
    local remote="$1"
    local remote_password1="$(get_password $remote)"
    local remote_password2="$(get_password2 $remote)"

    if [[ -z "$remote_password1" || -z "$remote_password2" ]]
    then
        echo "Could not determine password and/or salt value from config" >&2
        exit 6
    fi

    if grep "\[local-crypt\]" "$RCLONE_CONFIG" >/dev/null 2>&1
    then
        echo "The [local-crypt] remote is already present in config file. Abort." >&2
        exit 7
    fi

    # Backup current config
    cp "$RCLONE_CONFIG" "${RCLONE_CONFIG}.bak"

    cat >> "$RCLONE_CONFIG" <<-EoM

# Generated by $(basename $0)
[local]
type = local
nounc = 

[local-crypt]
type = crypt
remote = local:$RCLONE_LOCAL_DIR
filename_encryption = off
password = $remote_password1
password2 = $remote_password2
EoM
}

list_remotes() {
    awk '/\[.*\]/ { gsub("\\[|\\]","",$1); print $1}' "$RCLONE_CONFIG"
}

if [[ $# -lt 1 ]]
then
    usage
    exit 2
fi

RCLONE_CONFIG=~/.rclone.conf
# RCLONE_LOCAL_DIR="$(mktemp -d)"
RCLONE_LOCAL_DIR=~/.cache/rclone # Where the encrypted file will land
RCLONE_DECRYPT_DIR=~/.cache/rclone-decrypt # Where the file will be decrypted to
# Default remote name
REMOTE=acd-crypt

if grep -e '^'"${1}"'$' <<< "$(list_remotes)" >/dev/null 2>&1
then
    REMOTE="$1"
    shift
fi

FILE="$1"
FILE_DECRYPTED=$(basename "$FILE" .bin)

if [[ -n "$2" ]]
then
    DEST="$2"
else
    DEST="$PWD"
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

# Edit the rclone config to make the following command work
gen_config "$REMOTE"

# echo "RCLONE CONFIG"
# cat "$RCLONE_CONFIG"

mkdir -p "$RCLONE_LOCAL_DIR" "$RCLONE_DECRYPT_DIR"
cp -f "$FILE" "$RCLONE_LOCAL_DIR"

rclone mount local-crypt:/ "$RCLONE_DECRYPT_DIR" &
rclone_pid="$!"
trap "kill $rclone_pid >/dev/null 2>&1; sudo umount $RCLONE_DECRYPT_DIR 2>/dev/null; rm -rf $tmpdir $RCLONE_LOCAL_DIR; mv ${RCLONE_CONFIG}.bak $RCLONE_CONFIG" EXIT

# wait for file
echo -n "Waiting for file to be decrypted..."
while [[ ! -f "${RCLONE_DECRYPT_DIR}/${FILE_DECRYPTED}" ]]
do
    if ! kill -0 "$rclone_pid" 2> /dev/null
    then
        echo "rclone mount command failed" >&2
        exit 8
    fi
    sleep 2
    # FIXME Exit if rclone mount failed!
done
echo 'Done!'

echo -n "Copying file to destination..."
cp "${RCLONE_DECRYPT_DIR}/${FILE_DECRYPTED}" "$DEST"
echo  'Done!'
