# Security policy

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** (Security → Report a
vulnerability) rather than opening a public issue.

We acknowledge within a few working days. There is no bounty programme.

## What counts here

BC-250 BIOS Compare reads BIOS images that people download from forums and
pass around. It only reads them: it never writes to a chip. The things worth
reporting:

- a crafted BIOS image or dump that makes the parser (firmware volumes, LZMA
  sections, HII packages, IFR opcodes) crash, loop forever, exhaust memory,
  or run code;
- a crafted image that makes the comparison **lie**: shows two images as
  equal when they differ, or hides an entry that is there, so that someone
  flashes a modified image believing it is the one they checked;
- a path that makes the tool write anywhere outside the folder the user chose
  for an export.

## What does not count

- A BIOS setting that bricks a board when changed. The tool shows what the
  firmware contains; it does not decide what is safe to flash.
- The unsigned state of a build you made yourself.

## Supported versions

Only the latest release and `main` get fixes.
