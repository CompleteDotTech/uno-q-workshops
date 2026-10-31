"""Compile the actual sketch against small hardware stubs; no board is flashed."""

from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory


STUBS = r'''
#pragma once
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <string>
uint32_t clockMs = 0;
uint32_t displayDelay = 0;
uint32_t millis() { return clockMs; }
template<class T> T constrain(T n, T lo, T hi) { return std::max(lo, std::min(n, hi)); }
class String : public std::string {
public:
  using std::string::string;
  String& operator+=(const char* s) { append(s); return *this; }
  template<class T> String& operator+=(T n) { append(std::to_string(n)); return *this; }
};
struct ModulinoClass { void begin() {} } Modulino;
struct ModulinoKnob { bool down = false; void begin() {} bool isPressed() { return down; } };
struct ModulinoPixels {
  int count = 0;
  void begin() {} void clear() { count = 0; }
  void set(int, int, int, int, int) { count++; }
  void show() { clockMs += displayDelay; }
};
struct ModulinoVibro { int duration = 0; void begin() {} void on(int n) { duration = n; } };
struct BridgeClass { void begin() {} template<class T> void provide_safe(const char*, T) {} } Bridge;
'''

CHECKS = r'''
void drive(uint32_t at, bool down) { clockMs = at; knob.down = down; loop(); }
void clearButton(uint32_t at) {
  clockMs = lastSampleAt = rawChangedAt = at;
  knob.down = rawPressed = pressed = false;
  eventCount = 0; overflowed = false;
}
void check() {
  setup(); clearButton(100);
  drive(110, true); drive(120, false); drive(130, true);
  assert(eventCount == 0);
  drive(150, true); assert(eventCount == 1 && events[0].at == 130);
  drive(230, false); drive(250, false);
  assert(poll_input() == "[230,0,0,[[1,130],[0,230]]]");
  assert(eventCount == 0 && !overflowed);
  // A pending press at gap 990ms must arrive before the consumer's 1000ms deadline.
  drive(1220, true); drive(1230, true);
  assert(poll_input() == "[1210,0,0,[]]");
  drive(1240, true);
  assert(poll_input() == "[1220,1,0,[[1,1220]]]");
  // Releasing at 2990ms must not become a three-second reset during debounce.
  clearButton(2000); drive(2010, true); drive(2030, true); poll_input();
  drive(5000, false); drive(5010, false);
  assert(poll_input() == "[4990,1,0,[]]");
  drive(5020, false);
  assert(poll_input() == "[5000,0,0,[[0,5000]]]");
  clearButton(6000);
  for (int i = 0; i < 34; i++) {
    drive(6100 + i * 50, i % 2 == 0); drive(6120 + i * 50, i % 2 == 0);
  }
  assert(eventCount == 32 && overflowed);
  poll_input(); assert(eventCount == 0 && !overflowed);
  clearButton(0xFFFFFFD0u);
  drive(0xFFFFFFE0u, true); drive(0xFFFFFFF4u, true);
  drive(40, false); drive(60, false);
  assert(eventCount == 2 && uint32_t(events[1].at - events[0].at) == 72);
}
void checkPrompt() {
  clockMs = 100; displayDelay = 17;
  assert(show(4, 2) == 117);
  assert(pixels.count == 2);
  displayDelay = 0;
}
int main() { check(); checkPrompt(); }
'''


def check():
    compiler = shutil.which("c++")
    if compiler is None:
        print("SKIP: host sketch simulation requires a C++17 compiler")
        return
    sketch = Path(__file__).resolve().parent / "workshop-app/sketch/sketch.ino"
    with TemporaryDirectory(prefix="uno-q-sketch-") as directory:
        temp = Path(directory)
        (temp / "Arduino_Modulino.h").write_text(STUBS)
        (temp / "Arduino_RouterBridge.h").write_text("#pragma once\n")
        source = temp / "check.cpp"
        source.write_text(f'#include "{sketch}"\n' + CHECKS)
        executable = temp / "check"
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(temp),
                        str(source), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True, cwd=temp)
    print("PASS: sketch host simulation (stubbed Arduino hardware; not a board compilation)")


if __name__ == "__main__":
    check()
