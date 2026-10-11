package dev.noshorts.core;

/** Keep a detected blocked page covered while Chrome hides its address bar. */
public final class Guard {
    private boolean blocked;
    public boolean observe(UrlRules.Verdict verdict) {
        if (verdict == UrlRules.Verdict.BLOCK) blocked = true;
        else if (verdict == UrlRules.Verdict.ALLOW) blocked = false;
        return blocked;
    }
    public boolean isBlocked() { return blocked; }
    /** Called only when intentionally opening the fixed safe YouTube home URL. */
    public void openSafeHome() { blocked = false; }
}
