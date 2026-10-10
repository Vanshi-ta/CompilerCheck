// compilercheck: category=functions safety=well_defined expect_exit=0
#include <cstdio>

template <typename T>
T square(T v) { return v * v; }

struct Guard {
    int id;
    explicit Guard(int i) : id(i) { std::printf("enter %d\n", id); }
    ~Guard() { std::printf("leave %d\n", id); }
};

int main() {
    Guard outer(1);
    {
        Guard inner(2);
        std::printf("%d %.2f\n", square(7), square(1.5));
    }
    return 0;
}
