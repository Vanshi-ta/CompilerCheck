// compilercheck: category=undefined_behavior safety=undefined_behavior description="implementation-defined behavior"
// Right-shifting a negative value, the signedness of plain char and sizeof(long) are
// implementation-defined: they are documented per platform, not undefined, but they differ
// between platforms and ABIs, so cross-compiler comparisons need care.
#include <stdio.h>

int main(void) {
    int neg = -16;
    char c = (char)200;
    printf("%d\n%d\n%d\n", neg >> 2, (int)c, (int)sizeof(long));
    return 0;
}
