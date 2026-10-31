#include <Arduino_Modulino.h>
#include <Arduino_RouterBridge.h>

ModulinoKnob knob;
ModulinoPixels pixels;
ModulinoVibro vibro;

const uint32_t SAMPLE_MS = 5;
const uint32_t DEBOUNCE_MS = 20;
const int EVENT_CAPACITY = 32;
struct Edge { int pressed; uint32_t at; };
Edge events[EVENT_CAPACITY];
int eventCount = 0;
bool overflowed = false;
bool pressed = false;
bool rawPressed = false;
uint32_t rawChangedAt = 0;
uint32_t lastSampleAt = 0;

uint32_t show(int color, int count) {
  const uint8_t colors[][3] = {
    {0, 120, 220}, {220, 40, 120}, {40, 200, 80}, {120, 70, 220},
    {220, 220, 220}, {230, 150, 0}, {220, 0, 0}, {0, 0, 0}
  };
  color = constrain(color, 0, 7);
  count = constrain(count, 0, 8);
  pixels.clear();
  for (int i = 0; i < count; i++) {
    pixels.set(i, colors[color][0], colors[color][1], colors[color][2], 25);
  }
  pixels.show();
  return millis();
}

void pulse(int duration) {
  vibro.on(constrain(duration, 20, 600));
}

String poll_input() {
  String result = "[";
  // Consumer deadlines must wait for transitions still being debounced.
  result += uint32_t(lastSampleAt - DEBOUNCE_MS);
  result += ",";
  result += pressed ? 1 : 0;
  result += ",";
  result += overflowed ? 1 : 0;
  result += ",[";
  for (int i = 0; i < eventCount; i++) {
    if (i) result += ",";
    result += "[";
    result += events[i].pressed;
    result += ",";
    result += events[i].at;
    result += "]";
  }
  result += "]]";
  eventCount = 0;
  overflowed = false;
  return result;
}

void setup() {
  Modulino.begin();
  knob.begin();
  pixels.begin();
  vibro.begin();
  pressed = rawPressed = knob.isPressed();
  rawChangedAt = lastSampleAt = millis();
  show(0, 8);
  pulse(120);
  Bridge.begin();
  Bridge.provide_safe("poll_input", poll_input);
  Bridge.provide_safe("show", show);
  Bridge.provide_safe("pulse", pulse);
}

void loop() {
  uint32_t now = millis();
  if (uint32_t(now - lastSampleAt) < SAMPLE_MS) return;
  lastSampleAt = now;
  bool reading = knob.isPressed();
  if (reading != rawPressed) {
    rawPressed = reading;
    rawChangedAt = now;
  }
  if (rawPressed != pressed && uint32_t(now - rawChangedAt) >= DEBOUNCE_MS) {
    pressed = rawPressed;
    if (eventCount < EVENT_CAPACITY) {
      events[eventCount++] = {pressed ? 1 : 0, rawChangedAt};
    } else {
      overflowed = true;
    }
  }
}
