# Contributing

Thanks for looking. People use this tool to decide what to flash on a board
they cannot easily replace, so correctness comes before everything.

## The rules that matter

- **Never show more certainty than the firmware gives.** If an entry's
  condition cannot be evaluated, the window says so; it does not guess.
- **Every offset and length read from an image is untrusted.** Images come
  from forums. Check them against the data before following them.
- **Python standard library only.** The tool runs with a plain Python 3 and
  nothing to install; keep it that way.

## Before a pull request

- try the change on at least two real BC-250 images, stock and modified;
- no credentials anywhere: `bash scripts/check-secrets.sh` must say so. The
  same check runs in CI on every push.

## Licence

By contributing you agree your change is released under this repository's
licence (see LICENSE).
