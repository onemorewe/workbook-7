package dev.noshorts.core;

import java.net.IDN;
import java.net.URI;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** Matches host + path, never a page title, query string, or substring of a hostname. */
public final class UrlRules {
    public enum Verdict { ALLOW, BLOCK, UNKNOWN }
    private final List<Rule> extra;

    public UrlRules(String lines) {
        List<Rule> rules = new ArrayList<>();
        for (String line : lines.split("\\R")) {
            String value = line.trim();
            if (value.isEmpty() || value.startsWith("#")) continue;
            Address a = parse(value);
            if (a == null || a.internal || value.indexOf('?') >= 0 || value.indexOf('#') >= 0)
                throw new IllegalArgumentException("Нужно правило домен/путь без ? и #: " + value);
            rules.add(new Rule(a.host, a.path));
            if (rules.size() > 100) throw new IllegalArgumentException("Не больше 100 правил");
        }
        extra = Collections.unmodifiableList(rules);
    }

    public Verdict evaluate(String displayedAddress) {
        Address a = parse(displayedAddress);
        if (a == null) return Verdict.UNKNOWN;
        if (a.internal) return Verdict.ALLOW;
        if (new Rule("youtube.com", "/shorts").matches(a)) return Verdict.BLOCK;
        for (Rule r : extra) if (r.matches(a)) return Verdict.BLOCK;
        return Verdict.ALLOW;
    }

    private static Address parse(String input) {
        if (input == null) return null;
        String text = input.trim();
        if (text.isEmpty() || text.length() > 8192 || text.chars().anyMatch(Character::isWhitespace)) return null;
        // Chrome's own pages are safe to leave accessible, including Settings and New Tab.
        if (text.equals("about:blank") || text.startsWith("chrome://"))
            return new Address("", "/", true);
        if (text.startsWith("//")) text = "https:" + text;
        if (!text.contains("://")) text = "https://" + text;
        try {
            URI u = new URI(text);
            String scheme = u.getScheme();
            if (!"https".equalsIgnoreCase(scheme) && !"http".equalsIgnoreCase(scheme)) return null;
            String host = u.getHost();
            if (host == null || host.isEmpty()) return null;
            if (!host.contains(".") && !host.contains(":") && !host.equalsIgnoreCase("localhost")) return null;
            if (u.getPort() > 65535) return null;
            host = IDN.toASCII(host).toLowerCase(Locale.ROOT);
            while (host.endsWith(".")) host = host.substring(0, host.length() - 1);
            String decoded = u.getPath();
            if (decoded == null || decoded.isEmpty()) decoded = "/";
            // Normalize dot segments and duplicated slashes after one URL decoding pass.
            List<String> segments = new ArrayList<>();
            for (String segment : decoded.split("/")) {
                if (segment.isEmpty() || segment.equals(".")) continue;
                if (segment.equals("..")) { if (!segments.isEmpty()) segments.remove(segments.size()-1); }
                else segments.add(segment);
            }
            return new Address(host, "/" + String.join("/", segments), false);
        } catch (Exception ex) { return null; }
    }

    private static final class Address {
        final String host, path;
        final boolean internal;
        Address(String host, String path, boolean internal) { this.host=host; this.path=path; this.internal=internal; }
    }
    private static final class Rule {
        final String host, path;
        Rule(String host, String path) { this.host=host; this.path=path; }
        boolean matches(Address a) {
            boolean sameHost = a.host.equals(host) || a.host.endsWith("." + host);
            return sameHost && (path.equals("/") || a.path.equals(path) || a.path.startsWith(path + "/"));
        }
    }
}
