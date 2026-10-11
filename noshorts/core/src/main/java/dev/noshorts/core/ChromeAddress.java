package dev.noshorts.core;

/** Adapts only the unfocused native Chrome url_bar node, never page text or titles. */
public final class ChromeAddress {
    private ChromeAddress() {}
    public static String fromNodeText(String value) {
        if(value==null) return null;
        // Chromium UrlBar appends localized warnings using "%s. %s".
        // Canonical URLs contain no whitespace; preserve the exact URL before that separator.
        int separator=value.indexOf(". ");
        if(separator<=0 || value.substring(separator+2).trim().isEmpty()) return value;
        String address=value.substring(0,separator);
        if(address.chars().anyMatch(Character::isWhitespace)) return value;
        return address;
    }
}
