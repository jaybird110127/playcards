/*
 * fmlog2wav - turn a captured YM2151 register stream into audio.
 *
 *     fmlog2wav in.fmlog out.wav [options]
 *
 *         --rate N        output sample rate, default 44100
 *         --normalize     bring the loudest peak up to -0.5 dBFS
 *         --gain G        a fixed multiplier instead
 *         --no-trim       keep the silence at both ends
 *         --skip SECONDS  drop this much from the front before anything else
 *
 * Silence is trimmed from both ends by default, which matters here: a capture
 * begins with the machine booting and the card being read, neither of which
 * makes a sound, so a card's audio typically starts sixteen seconds in.
 *
 * An .fmlog is what playcard.exe (or msx_player.py) writes while a card plays:
 * one line a write, "seconds register value", with the seconds taken from the
 * Z80's own cycle count.  Rendering it is then just "advance the chip to the
 * time of the next write, apply it, repeat" - the hard part is the chip, and
 * that is ymfm (BSD 3-clause, see ymfm/YMFM_LICENSE), which is the same core
 * MAME uses.  Nothing here models FM synthesis; it only drives it.
 *
 * The chip runs at its real 3.579545 MHz, which gives a native sample rate of
 * clock/64 = 55930 Hz.  Output is resampled to the requested rate by linear
 * interpolation, which is inaudible against the chip's own aliasing.
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <vector>
#include <string>

#include "ymfm/ymfm_opm.h"

static const double OPM_CLOCK = 3579545.0;

/* ymfm calls back into this for timers and IRQ; a renderer needs none of it,
 * because the log already contains everything the chip was told. */
class silent_interface : public ymfm::ymfm_interface
{
};

struct fmevent {
    double t;
    uint8_t reg, val;
};

static void put32(std::vector<uint8_t> &v, uint32_t x)
{
    v.push_back(x & 0xFF); v.push_back((x >> 8) & 0xFF);
    v.push_back((x >> 16) & 0xFF); v.push_back((x >> 24) & 0xFF);
}

static void put16(std::vector<uint8_t> &v, uint16_t x)
{
    v.push_back(x & 0xFF); v.push_back((x >> 8) & 0xFF);
}

static void usage(void)
{
    fprintf(stderr,
        "usage: fmlog2wav in.fmlog out.wav [options]\n"
        "   --rate N        output sample rate, default 44100\n"
        "   --normalize     bring the loudest peak up to -0.5 dBFS\n"
        "   --gain G        a fixed multiplier instead\n"
        "   --no-trim       keep the silence at both ends\n"
        "   --skip SECONDS  drop this much from the front first\n");
}

int main(int argc, char **argv)
{
    const char *in = NULL, *out = NULL;
    int rate = 44100;
    double gain = 1.0;
    double skip = 0.0;          /* seconds of lead-in to drop before trimming */
    int normalize = 0, trim = 1;
    const double TARGET = 0.944;    /* -0.5 dBFS, a little short of clipping */
    const double PAD = 0.05;        /* seconds kept either side of the audio */

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--rate") && i + 1 < argc) rate = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--gain") && i + 1 < argc) gain = atof(argv[++i]);
        else if (!strcmp(argv[i], "--skip") && i + 1 < argc) skip = atof(argv[++i]);
        else if (!strcmp(argv[i], "--normalize") || !strcmp(argv[i], "-n")) normalize = 1;
        else if (!strcmp(argv[i], "--no-trim")) trim = 0;
        else if (argv[i][0] == '-') { usage(); return 2; }
        else if (!in) in = argv[i];
        else out = argv[i];
    }
    if (!in || !out) {
        usage();
        return 2;
    }

    /* ---- read the capture ---- */
    std::vector<fmevent> ev;
    {
        FILE *f = fopen(in, "r");
        if (!f) { fprintf(stderr, "fmlog2wav: cannot read %s\n", in); return 1; }
        char line[256];
        while (fgets(line, sizeof line, f)) {
            double t; unsigned r, v;
            if (sscanf(line, "%lf %x %x", &t, &r, &v) == 3) {
                fmevent e; e.t = t; e.reg = (uint8_t)r; e.val = (uint8_t)v;
                ev.push_back(e);
            }
        }
        fclose(f);
    }
    if (ev.empty()) { fprintf(stderr, "fmlog2wav: %s has no writes\n", in); return 1; }

    double duration = ev.back().t + 1.0;      /* a second of tail for releases */
    printf("%s: %zu register writes over %.2f s\n", in, ev.size(), ev.back().t);

    /* ---- render at the chip's own rate ---- */
    silent_interface iface;
    ymfm::ym2151 opm(iface);
    opm.reset();
    uint32_t native = opm.sample_rate((uint32_t)OPM_CLOCK);
    printf("  ymfm ym2151 at %.0f Hz clock -> %u Hz native\n", OPM_CLOCK, native);

    size_t total = (size_t)(duration * native);
    std::vector<float> left(total, 0.0f), right(total, 0.0f);
    ymfm::ym2151::output_data frame;

    size_t next = 0;
    for (size_t i = 0; i < total; i++) {
        double now = (double)i / native;
        while (next < ev.size() && ev[next].t <= now) {
            opm.write_address(ev[next].reg);
            opm.write_data(ev[next].val);
            next++;
        }
        opm.generate(&frame, 1);
        left[i] = frame.data[0] / 32768.0f;
        right[i] = frame.data[1] / 32768.0f;
    }

    /* ---- find where the audio actually is ---- */
    size_t lo = (size_t)(skip * native);
    size_t hi = total;
    if (lo > total) lo = total;

    double peak = 0.0;
    for (size_t i = lo; i < hi; i++) {
        double l = left[i] < 0 ? -left[i] : left[i];
        double r = right[i] < 0 ? -right[i] : right[i];
        if (l > peak) peak = l;
        if (r > peak) peak = r;
    }

    if (trim && peak > 0.0) {
        /* A thousandth of the loudest peak.  The chip emits exact zeros when
         * nothing sounds, so this only has to clear the quietest real note
         * rather than any noise floor. */
        double thr = peak * 0.001;
        size_t a = lo, b = hi;
        while (a < hi) {
            double l = left[a] < 0 ? -left[a] : left[a];
            double r = right[a] < 0 ? -right[a] : right[a];
            if (l > thr || r > thr) break;
            a++;
        }
        while (b > a) {
            double l = left[b - 1] < 0 ? -left[b - 1] : left[b - 1];
            double r = right[b - 1] < 0 ? -right[b - 1] : right[b - 1];
            if (l > thr || r > thr) break;
            b--;
        }
        if (a < b) {
            size_t pad = (size_t)(PAD * native);
            lo = (a > lo + pad) ? a - pad : lo;
            hi = (b + pad < hi) ? b + pad : hi;
            printf("  trimmed to %.2f s .. %.2f s of the capture\n",
                   (double)lo / native, (double)hi / native);
        }
    }

    if (normalize) {
        if (peak > 0.0) {
            gain = TARGET / peak;
            printf("  normalised: peak was %.3f of full scale, gain x%.2f\n",
                   peak, gain);
        } else {
            printf("  nothing to normalise: the capture is silent\n");
        }
    }

    /* ---- resample and write ---- */
    size_t span = (hi > lo) ? hi - lo : 0;
    size_t outn = (size_t)((double)span / native * rate);
    std::vector<uint8_t> body;
    body.reserve(outn * 4);
    double outpeak = 0.0;
    for (size_t i = 0; i < outn; i++) {
        double src = (double)i * native / rate;
        size_t j = lo + (size_t)src;
        double frac = src - (size_t)src;
        if (j + 1 >= total) break;
        double l = (left[j] + (left[j + 1] - left[j]) * frac) * gain;
        double r = (right[j] + (right[j + 1] - right[j]) * frac) * gain;
        if (l > outpeak) outpeak = l;
        if (-l > outpeak) outpeak = -l;
        int li = (int)(l * 32767.0);
        int ri = (int)(r * 32767.0);
        if (li > 32767) li = 32767;
        if (li < -32768) li = -32768;
        if (ri > 32767) ri = 32767;
        if (ri < -32768) ri = -32768;
        put16(body, (uint16_t)(int16_t)li);
        put16(body, (uint16_t)(int16_t)ri);
    }

    std::vector<uint8_t> hdr;
    const char *riff = "RIFF"; hdr.insert(hdr.end(), riff, riff + 4);
    put32(hdr, (uint32_t)(36 + body.size()));
    const char *wave = "WAVEfmt "; hdr.insert(hdr.end(), wave, wave + 8);
    put32(hdr, 16);
    put16(hdr, 1);                      /* PCM */
    put16(hdr, 2);                      /* stereo */
    put32(hdr, rate);
    put32(hdr, rate * 4);
    put16(hdr, 4);
    put16(hdr, 16);
    const char *data = "data"; hdr.insert(hdr.end(), data, data + 4);
    put32(hdr, (uint32_t)body.size());

    FILE *f = fopen(out, "wb");
    if (!f) { fprintf(stderr, "fmlog2wav: cannot write %s\n", out); return 1; }
    fwrite(hdr.data(), 1, hdr.size(), f);
    fwrite(body.data(), 1, body.size(), f);
    fclose(f);
    printf("  wrote %s: %.2f s, %d Hz stereo, peak %.2f of full scale\n",
           out, (double)(body.size() / 4) / rate, rate, outpeak);
    return 0;
}
