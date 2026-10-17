# Plymouth mouse pointer (experimental)

A patched Plymouth that draws a mouse pointer on the boot screen, including the
LUKS password prompt. Mice, touchpads, tablets and touch screens work. Themes
written for the `script` module can also read the pointer (see below).

Install with `experimental/enable-plymouth-pointer.sh`, undo with
`experimental/disable-plymouth-pointer.sh`. Both are documented in their headers.

## What is here

| File | What |
| --- | --- |
| `files/` | The four rebuilt files: `libply-splash-core.so.5.0.0`, `plymouth/renderers/drm.so`, `plymouth/renderers/frame-buffer.so`, `plymouth/script.so` |
| `SHA256SUMS` | Checked by the enable script before anything is touched |
| `plymouth-pointer.patch` | Full source change against Debian's `plymouth 24.004.60-5` (unified diff, `patch -p1`) |

Plymouth is GPL-2+, and so is the patch. The binaries are built from exactly
this patch, so the source for what the machine runs is in this directory.

## How it works

* The pointer is drawn into the framebuffer by Plymouth itself (the old contents
  are put back from the splash's pixel buffer, then the arrow is drawn on top),
  not with a hardware cursor plane. Hardware cursors only reach the screen on a
  real display controller; VM windows, remote consoles and drivers without a
  cursor plane would show nothing. `plymouth.hardware-pointer` on the kernel
  command line switches the DRM renderer to the hardware plane.
* Input comes from evdev. Debian's initramfs has neither the xkb keymap data nor
  the `evdev` module, so stock Plymouth takes keyboards from the console there
  and never opens an input device. This build opens pointer devices without a
  keymap and leaves the keyboards on the console, so typing a password works as
  before. The enable script adds `evdev` to the initramfs module list.
* Devices: relative (mice, trackpoints), absolute (tablets, touch screens, VM
  pointers) and touchpads. A touchpad moves the pointer by finger movement
  (10 px per mm of travel, one finger only), a touch on it is not a click, a
  press of its button is.
* `plymouth.disable-pointer` on the kernel command line turns it off for a boot.

## For theme authors (script module)

```
Plymouth.SetPointerMotionFunction (fun (x, y) { ... });
Plymouth.SetPointerButtonFunction (fun (button, pressed, x, y) { ... });
Plymouth.GetPointerX ();  Plymouth.GetPointerY ();
```

Coordinates are in the same space as sprites. `button` is 1 (left or touch),
2 (right) or 3 (middle), `pressed` is 1 or 0. The pointer only appears after the
first movement.

## Also in the patch

Ctrl+F at the password prompt no longer lands in the password field; the key
still reaches the theme script's keyboard function (used by Boot Fresh).

## Rebuilding

```
apt-get source plymouth                      # 24.004.60-5, needs deb-src
sudo apt-get install meson ninja-build libdrm-dev libevdev-dev libudev-dev \
  systemd-dev libpng-dev libpango1.0-dev libgtk-3-dev libcairo2-dev docbook-xsl xsltproc gettext
cd plymouth-24.004.60 && patch -p1 < .../plymouth-pointer.patch
meson setup ../build --prefix=/usr -Dtracing=true && ninja -C ../build
DESTDIR=$PWD/../stage ninja -C ../build install
```

Copy the four files out of `stage/usr/lib/x86_64-linux-gnu/` into `files/` and
regenerate `SHA256SUMS`. Build options for testing: `-Dc_args=-DPLY_POINTER_MIRRORED=1`
flips the arrow, `-Dc_args=-DPLY_POINTER_FILL_COLOR=0xffff0000` recolours it.

A VM test harness (QEMU with a minimal initramfs, virtual mouse, tablet and
touchpad through uinput) exists outside this repository; ask before relying on
the binaries for anything beyond testing.

## Known limits

* Only tested on Plymouth 24.004.60-5 and on one Intel laptop (Synaptics
  touchpad) plus QEMU.
* An `apt upgrade` of plymouth or libplymouth5 replaces the files; run the enable
  script again.
* Rotated panels are not handled.
