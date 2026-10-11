package dev.noshorts.core;

public final class CoreTest {
    private static int checks;
    private static void expect(UrlRules r, String s, UrlRules.Verdict v) {
        checks++;
        if (r.evaluate(s) != v) throw new AssertionError(s + ": " + r.evaluate(s) + " != " + v);
    }
    private static void check(boolean value, String message) { checks++; if(!value) throw new AssertionError(message); }
    public static void main(String[] args) {
        UrlRules r = new UrlRules("");
        String[] blocked={"https://youtube.com/shorts", "youtube.com/shorts/abc", "m.youtube.com/shorts/abc?feature=share",
            "https://www.youtube.com/shorts/abc#x", "HTTPS://WWW.YOUTUBE.COM/shorts/a", "//m.youtube.com/shorts/a",
            "https://youtube.com:443/shorts/a", "https://youtube.com./shorts/a", "https://youtube.com/%73horts/a",
            "https://youtube.com/a/../shorts/a", "https://youtube.com//shorts//a", "https://youtube.com/%2Fshorts/a"};
        String[] allowed={"https://youtube.com", "https://m.youtube.com/", "https://youtube.com/watch?v=shorts",
            "https://youtube.com/results?search_query=shorts", "https://youtube.com/@creator/shorts", "https://youtube.com/shortsFake",
            "https://youtube.com/shorts/../watch?v=x", "https://google.com/search?q=youtube.com/shorts/a",
            "https://youtube.com.evil.example/shorts/a", "https://notyoutube.com/shorts/a", "https://youtube.com@evil.example/shorts/a",
            "https://evil.example/?redirect=https://youtube.com/shorts/a", "chrome://newtab", "chrome://settings", "about:blank"};
        String[] unknown={null,"", "YouTube Shorts", "Shorts", "Search or type web address", "https://youtube.com/%zz",
            "javascript:alert(1)", "https://", "www.youtube.com /shorts/a"};
        for(String s:blocked) expect(r,s,UrlRules.Verdict.BLOCK);
        for(String s:allowed) expect(r,s,UrlRules.Verdict.ALLOW);
        for(String s:unknown) expect(r,s,UrlRules.Verdict.UNKNOWN);
        for(int i=0;i<300;i++) {
            expect(r,"https://m.youtube.com/watch?v="+i+"&query=shorts",UrlRules.Verdict.ALLOW);
            expect(r,"https://youtube.com.fake"+i+".example/shorts/a",UrlRules.Verdict.ALLOW);
        }
        UrlRules custom=new UrlRules("instagram.com/reel\n# entire website\ntiktok.com\n");
        expect(custom,"https://www.instagram.com/reel/abc",UrlRules.Verdict.BLOCK);
        expect(custom,"https://instagram.com/reelsFake",UrlRules.Verdict.ALLOW);
        expect(custom,"https://www.instagram.com/direct/inbox",UrlRules.Verdict.ALLOW);
        expect(custom,"https://m.tiktok.com/anything",UrlRules.Verdict.BLOCK);
        for(String bad:new String[]{"youtube.com/shorts?x=1","hello there","youtube.com/#watch","https://"}) {
            boolean rejected=false;
            try { new UrlRules(bad); } catch(IllegalArgumentException ex) { rejected=true; }
            check(rejected,"Invalid custom rule accepted: "+bad);
        }
        Guard g=new Guard();
        check(!g.observe(UrlRules.Verdict.UNKNOWN),"Unknown initial page must not block all Chrome");
        check(!g.observe(UrlRules.Verdict.ALLOW),"Home must stay accessible");
        check(g.observe(UrlRules.Verdict.BLOCK),"Shorts must block");
        check(g.observe(UrlRules.Verdict.UNKNOWN),"Hidden address must not unlock detected Shorts");
        check(!g.observe(UrlRules.Verdict.ALLOW),"A confirmed ordinary video must unlock");
        g.observe(UrlRules.Verdict.BLOCK); g.openSafeHome();
        check(!g.isBlocked(),"Fixed safe home must clear stale latch");
        check(g.observe(UrlRules.Verdict.BLOCK),"A redirect back to Shorts must re-block");
        UrlRules http=new UrlRules("127.0.0.1/shorts");
        expect(http,ChromeAddress.fromNodeText("127.0.0.1:8765/shorts/test. Connection is not secure"),UrlRules.Verdict.BLOCK);
        expect(http,ChromeAddress.fromNodeText("127.0.0.1:8765/safe. Connection is not secure"),UrlRules.Verdict.ALLOW);
        expect(http,ChromeAddress.fromNodeText("127.0.0.1:8765/shorts/test. Соединение не защищено"),UrlRules.Verdict.BLOCK);
        expect(r,ChromeAddress.fromNodeText("youtube.com/shorts/a. Connection is not secure"),UrlRules.Verdict.BLOCK);
        expect(r,ChromeAddress.fromNodeText("youtube.com/watch?v=shorts. Connection is not secure"),UrlRules.Verdict.ALLOW);
        expect(r,ChromeAddress.fromNodeText("youtube.com.evil.example/shorts/a. Connection is not secure"),UrlRules.Verdict.ALLOW);
        expect(r,ChromeAddress.fromNodeText("youtube.com/shorts.. Connection is not secure"),UrlRules.Verdict.ALLOW);
        expect(r,ChromeAddress.fromNodeText("youtube.com/shorts.%20ordinary. Connection is not secure"),UrlRules.Verdict.ALLOW);
        expect(r,ChromeAddress.fromNodeText("YouTube Shorts. Connection is not secure"),UrlRules.Verdict.UNKNOWN);
        expect(r,ChromeAddress.fromNodeText("www.youtube.com /shorts/a"),UrlRules.Verdict.UNKNOWN);
        expect(r,ChromeAddress.fromNodeText(null),UrlRules.Verdict.UNKNOWN);
        System.out.println("PASS: "+checks+" URL and guard regression checks");
    }
}
