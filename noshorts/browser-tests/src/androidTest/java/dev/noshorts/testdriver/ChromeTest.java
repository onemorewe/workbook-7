package dev.noshorts.testdriver;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Context;
import android.content.ComponentName;
import android.content.Intent;
import android.net.Uri;
import android.os.SystemClock;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Rect;
import android.view.MotionEvent;
import android.view.InputDevice;
import android.view.accessibility.AccessibilityNodeInfo;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.uiautomator.*;
import org.junit.*;
import org.junit.runner.RunWith;
import org.junit.runners.MethodSorters;
import java.io.File;
import java.io.FileWriter;
import java.util.ArrayList;
import java.util.List;
import java.util.function.BooleanSupplier;
import java.util.regex.Pattern;
import java.util.regex.Matcher;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.InputStream;
import java.io.FileOutputStream;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
public class ChromeTest {
    private UiDevice device;
    private Context app;
    @Before public void setup() throws Exception {
        Configurator.getInstance().setUiAutomationFlags(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
            .setWaitForIdleTimeout(500);
        Instrumentation instrumentation=InstrumentationRegistry.getInstrumentation();
        device=UiDevice.getInstance(instrumentation);
        app=instrumentation.getTargetContext();
        // Instrument this independent driver, never the production NoShorts process.
        // Host tests already enabled and verified the released service across update/reboot.
        await(()->state().connected,15000,"Released Accessibility service did not connect");
        setRules("");
    }
    @After public void evidence() throws Exception {
        File dir=new File(app.getExternalFilesDir(null),"ci-evidence"); dir.mkdirs();
        String suffix=Long.toString(System.currentTimeMillis());
        device.dumpWindowHierarchy(new File(dir,"hierarchy-"+suffix+".xml"));
        device.takeScreenshot(new File(dir,"screen-"+suffix+".png"));
        try(FileWriter writer=new FileWriter(new File(dir,"service-"+suffix+".txt"))) {
            writer.write(serviceDump());
        }
        AccessibilityNodeInfo root=InstrumentationRegistry.getInstrumentation().getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES).getRootInActiveWindow();
        try(FileWriter writer=new FileWriter(new File(dir,"chrome-nodes-"+suffix+".txt"))) {
            writeNodes(writer,root,0);
        } finally { if(root!=null) root.recycle(); }
        // Gradle uninstalls this driver after instrumentation; keep evidence outside its data.
        device.executeShellCommand("mkdir -p /sdcard/Download/noshorts-ci");
        device.executeShellCommand("cp -R "+dir.getAbsolutePath()+"/. /sdcard/Download/noshorts-ci/");
    }
    private void writeNodes(FileWriter writer,AccessibilityNodeInfo node,int depth) throws Exception {
        if(node==null || depth>60) return;
        Rect r=new Rect(); node.getBoundsInScreen(r);
        writer.write(depth+" "+node.getClassName()+" "+r+" target="+
            node.getExtras().getCharSequence("AccessibilityNodeInfo.targetUrl")+" url="+
            node.getExtras().getCharSequence("url")+" role="+
            node.getExtras().getCharSequence("AccessibilityNodeInfo.chromeRole")+
            " text="+node.getText()+" desc="+node.getContentDescription()+"\n");
        for(int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo child=node.getChild(i);
            try { writeNodes(writer,child,depth+1); }
            finally { if(child!=null) child.recycle(); }
        }
    }
    private static final String BLOCKER="dev.noshorts.chrome";
    private static final class ServiceState {
        final boolean connected,cover; final int transitions;
        ServiceState(boolean connected,int transitions,boolean cover) {
            this.connected=connected; this.transitions=transitions; this.cover=cover;
        }
    }
    private String serviceDump() {
        try { return device.executeShellCommand("dumpsys activity service dev.noshorts.chrome/.ShortsService"); }
        catch(Exception ex) { throw new AssertionError("Cannot read released service diagnostics",ex); }
    }
    private ServiceState state() {
        long deadline=SystemClock.uptimeMillis()+5000;
        String dump;
        do {
            dump=serviceDump();
            Matcher m=Pattern.compile("NoShorts connected=(true|false) transitions=(\\d+) cover=(true|false)").matcher(dump);
            if(m.find()) return new ServiceState(Boolean.parseBoolean(m.group(1)),Integer.parseInt(m.group(2)),Boolean.parseBoolean(m.group(3)));
            SystemClock.sleep(100);
        } while(SystemClock.uptimeMillis()<deadline);
        throw new AssertionError("Released service diagnostics unavailable: "+dump);
    }
    private int maskCount() {
        Matcher m=Pattern.compile("masks=(\\d+)").matcher(serviceDump());
        return m.find()?Integer.parseInt(m.group(1)):-1;
    }
    private int feedMaskCount() {
        Matcher m=Pattern.compile("feedMasks=(\\d+)").matcher(serviceDump());
        return m.find()?Integer.parseInt(m.group(1)):-1;
    }
    private String address() {
        UiObject2 bar=device.findObject(By.res("com.android.chrome","url_bar"));
        try { return bar==null?"":bar.getText(); } catch(StaleObjectException ignored) { return ""; }
    }
    private void injectFeed(String site) throws Exception { injectFeed(site,false); }
    private void injectFeed(String site,boolean login) throws Exception {
        injectFeed(site,login,false);
    }
    private void injectFeed(String site,boolean login,boolean compact) throws Exception {
        open("http://127.0.0.1:8765/feed-fixture-start?site="+site);
        assertNotNull("Feed fixture start unavailable",device.wait(Until.findObject(By.text("Allowed page")),20000));
        HttpURLConnection c=(HttpURLConnection)new URL("http://127.0.0.1:8765/inject-feed?site="+site+(login?"&login=1":"")+(compact?"&compact=1":"")).openConnection();
        c.setConnectTimeout(10000); c.setReadTimeout(35000);
        try {
            int code=c.getResponseCode();
            InputStream in=code==200?c.getInputStream():c.getErrorStream();
            String body=new String(in.readAllBytes(),java.nio.charset.StandardCharsets.UTF_8);
            assertEquals("CDP feed fixture failed: "+body,200,code);
        } finally { c.disconnect(); }
        if(!login) await(()->feedMaskCount()>0,10000,"Feed contents did not get a mask: "+site);
    }
    private UiObject2 webSearchField() {
        for(UiObject2 edit:device.findObjects(By.clazz("android.widget.EditText"))) {
            try {
                if(!"com.android.chrome:id/url_bar".equals(edit.getResourceName()) && !edit.getVisibleBounds().isEmpty()) return edit;
            } catch(StaleObjectException ignored) { }
        }
        return null;
    }
    private boolean visiblePassword() {
        AccessibilityNodeInfo root=InstrumentationRegistry.getInstrumentation()
            .getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES).getRootInActiveWindow();
        try { return passwordNode(root,0); }
        finally { if(root!=null) root.recycle(); }
    }
    private boolean passwordNode(AccessibilityNodeInfo node,int depth) {
        if(node==null || depth>60) return false;
        Rect r=new Rect();node.getBoundsInScreen(r);
        if(node.isPassword() && !r.isEmpty()) return true;
        for(int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo child=node.getChild(i);
            try { if(passwordNode(child,depth+1)) return true; }
            finally { if(child!=null) child.recycle(); }
        }
        return false;
    }
    private void assertCaptionPainted(String site) {
        // Non-touchable overlay windows are not interactive UiAutomator roots.
        // Check their actual rendered text; saved screenshots verify each name.
        await(()->{
            File frame=new File(app.getExternalFilesDir(null),"caption-check.png");
            assertTrue(device.takeScreenshot(frame));Bitmap shot=BitmapFactory.decodeFile(frame.getAbsolutePath());
            assertNotNull(shot);
            try {
                int ink=0;
                for(int y=shot.getHeight()/4;y<shot.getHeight()*3/4;y++)
                    for(int x=shot.getWidth()/10;x<shot.getWidth()*9/10;x++) {
                        int c=shot.getPixel(x,y);
                        if(Math.abs(Color.red(c)-244)<=2 && Math.abs(Color.green(c)-245)<=2 &&
                            Math.abs(Color.blue(c)-247)<=2) ink++;
                    }
                return ink>100;
            } finally { shot.recycle(); }
        },5000,"Feed caption was not painted: "+site);
    }
    private void dismissObservedChromeTip() {
        BySelector tip=By.res("com.android.chrome","message").text(Pattern.compile("(?s)Get the best of Gemini.*"));
        if(device.hasObject(tip)) {
            // The observed first-launch Chrome bubble intercepts taps on the web header.
            // Tap the fixture's inert middle area to close only this known browser tip.
            device.click(device.getDisplayWidth()/2,device.getDisplayHeight()/2);
            await(()->!device.hasObject(tip),5000,"Observed Chrome Gemini tip did not dismiss");
        }
    }
    private Rect corner(Rect r) { return new Rect(r.left+5,r.top+5,r.left+7,r.top+7); }
    private void feedEvidence(String site,String suffix) throws Exception {
        File dir=new File(app.getExternalFilesDir(null),"ci-evidence");dir.mkdirs();
        device.takeScreenshot(new File(dir,"feed-"+site+suffix+".png"));
        device.dumpWindowHierarchy(new File(dir,"feed-"+site+suffix+".xml"));
        AccessibilityNodeInfo root=InstrumentationRegistry.getInstrumentation()
            .getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES).getRootInActiveWindow();
        try(FileWriter writer=new FileWriter(new File(dir,"feed-"+site+suffix+"-nodes.txt"))) { writeNodes(writer,root,0); }
        finally { if(root!=null) root.recycle(); }
    }
    private void assertPainted(Rect r,int expected,String label) {
        await(()->painted(r,expected),7000,label);
    }
    private boolean painted(Rect r,int expected) {
        File frame=new File(app.getExternalFilesDir(null),"pixel-check.png");
        assertTrue("Screenshot capture failed",device.takeScreenshot(frame));
        Bitmap shot=BitmapFactory.decodeFile(frame.getAbsolutePath());
        assertNotNull("Screenshot unavailable",shot);
        try {
            if(r.width()<=0 || r.height()<=0) return false;
            int x=Math.min(shot.getWidth()-1,Math.max(0,r.centerX()*shot.getWidth()/device.getDisplayWidth()));
            int y=Math.min(shot.getHeight()-1,Math.max(0,r.centerY()*shot.getHeight()/device.getDisplayHeight()));
            int actual=shot.getPixel(x,y);
            boolean match=Math.abs(Color.red(expected)-Color.red(actual))<=2 &&
                Math.abs(Color.green(expected)-Color.green(actual))<=2 &&
                Math.abs(Color.blue(expected)-Color.blue(actual))<=2;
            if(!match) System.out.println("Pixel mismatch: bounds="+r+" bitmap="+shot.getWidth()+"x"+
                shot.getHeight()+" sample="+x+","+y+" actual="+Integer.toHexString(actual));
            return match;
        } finally { shot.recycle(); }
    }
    private UiObject2 visible(BySelector selector) {
        UiObject2 node=device.findObject(selector);
        if(node==null) return null;
        try { Rect r=node.getVisibleBounds(); return r.width()>0 && r.height()>0?node:null; }
        catch(StaleObjectException ignored) { return null; }
    }
    private List<Rect> liveShortsCards() {
        List<Rect> result=new ArrayList<>();
        AccessibilityNodeInfo root=InstrumentationRegistry.getInstrumentation().getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES).getRootInActiveWindow();
        try { collectCards(root,result,0); }
        finally { if(root!=null) root.recycle(); }
        return result;
    }
    private void collectCards(AccessibilityNodeInfo node,List<Rect> result,int depth) {
        if(node==null || depth>60) return;
        CharSequence url=node.getExtras().getCharSequence("AccessibilityNodeInfo.targetUrl");
        if(url!=null) {
            Uri target=Uri.parse(url.toString());
            String host=target.getHost(),path=target.getPath();
            if(host!=null && (host.equals("youtube.com") || host.endsWith(".youtube.com")) &&
                path!=null && path.startsWith("/shorts/")) {
                Rect r=new Rect(); node.getBoundsInScreen(r);
                if(r.width()>device.getDisplayWidth()/5 && r.height()>device.getDisplayHeight()/12 &&
                    r.top>=0 && r.bottom<=device.getDisplayHeight()) result.add(r);
            }
        }
        for(int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo child=node.getChild(i);
            try { collectCards(child,result,depth+1); }
            finally { if(child!=null) child.recycle(); }
        }
    }
    private UiObject2 blockerControl(String id) {
        for(int attempt=0;attempt<10;attempt++) {
            UiObject2 control=device.findObject(By.res(BLOCKER,id));
            if(control!=null) return control;
            device.swipe(device.getDisplayWidth()/2,device.getDisplayHeight()*3/4,
                device.getDisplayWidth()/2,device.getDisplayHeight()/3,20);
            SystemClock.sleep(300);
        }
        throw new AssertionError("NoShorts control unavailable: "+id);
    }
    private void setRules(String value) {
        app.startActivity(new Intent().setComponent(new ComponentName(BLOCKER,BLOCKER+".MainActivity"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        assertTrue("NoShorts settings did not open",device.wait(Until.hasObject(By.pkg(BLOCKER)),5000));
        blockerControl("rules_input").setText(value);
        if(device.hasObject(By.pkg("com.google.android.inputmethod.latin"))) device.pressBack();
        blockerControl("save_rules").click();
        SystemClock.sleep(300);
    }
    private void open(String url) {
        app.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url)).setPackage("com.android.chrome")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
    }
    private void await(BooleanSupplier condition,long timeout,String message) {
        long deadline=SystemClock.uptimeMillis()+timeout;
        while(SystemClock.uptimeMillis()<deadline) {
            if(condition.getAsBoolean()) return;
            SystemClock.sleep(100);
        }
        UiObject2 bar=device.findObject(By.res("com.android.chrome","url_bar"));
        throw new AssertionError(message+"; url_bar="+(bar==null?"<missing>":bar.getText())+
            "; connected="+state().connected+"; transitions="+state().transitions+"; cover="+state().cover);
    }
    private void home() {
        open("https://m.youtube.com/results?search_query=music");
        long deadline=SystemClock.uptimeMillis()+30000;
        while(SystemClock.uptimeMillis()<deadline) {
            UiObject2 onboarding=device.findObject(By.res("com.android.chrome","signin_fre_dismiss_button"));
            if(onboarding==null) onboarding=device.findObject(By.text(Pattern.compile("(?i)(stay signed out|continue without an account|use without an account|accept & continue|no thanks|not now|got it|skip)")));
            if(onboarding!=null) {
                try { onboarding.click(); } catch(StaleObjectException ignored) { continue; }
            }
            UiObject2 current=device.findObject(By.res("com.android.chrome","url_bar"));
            if(current!=null && onboarding==null && !state().cover &&
                "com.android.chrome".equals(device.getCurrentPackageName())) {
                try { if(current.getText().contains("/results")) break; }
                catch(StaleObjectException ignored) { }
            }
            SystemClock.sleep(300);
        }
        assertTrue("Chrome address bar unavailable",device.hasObject(By.res("com.android.chrome","url_bar")));
        assertEquals("Chrome did not become the foreground app","com.android.chrome",device.getCurrentPackageName());
    }
    private void blockedOutcome(int before,String message) {
        await(()->state().transitions>before,20000,message);
        await(()->{
            if(device.hasObject(By.text("Этот раздел заблокирован"))) return true;
            UiObject2 bar=device.findObject(By.res("com.android.chrome","url_bar"));
            return bar==null || !bar.getText().contains("/shorts");
        },7000,"Shorts still exposed after detection");
    }
    @Test public void test01OrdinaryYouTubeIsAllowed() {
        home(); int before=state().transitions;
        open("https://m.youtube.com/results?search_query=shorts");
        SystemClock.sleep(5000);
        assertEquals("Search was falsely blocked",before,state().transitions);
        assertFalse("Search is covered",state().cover);
        open("https://m.youtube.com/watch?v=wmzbgQAqjvI");
        SystemClock.sleep(5000);
        assertEquals("Ordinary player was falsely blocked",before,state().transitions);
        assertFalse("Ordinary player is covered",state().cover);
    }
    @Test public void test02DirectShortsIsBlocked() {
        home(); int before=state().transitions;
        open("https://m.youtube.com/shorts/wmzbgQAqjvI");
        blockedOutcome(before,"Direct YouTube Shorts was not detected");
        device.pressHome();
        await(()->!state().cover,3000,"Cover leaked outside Chrome");
    }
    @Test public void test03YouTubeNavigationIsBlocked() {
        home();
        UiObject2 shorts=device.wait(Until.findObject(By.text("Shorts")),25000);
        if(shorts==null) shorts=device.findObject(By.desc("Shorts"));
        assertNotNull("Live YouTube Shorts entry was not available; this test must not be silently skipped",shorts);
        int before=state().transitions;
        shorts.click();
        blockedOutcome(before,"YouTube in-page Shorts navigation was not blocked");
    }
    @Test public void test04ChromeHistoryApiAndCustomPath() {
        home();
        setRules("127.0.0.1/shorts");
        open("http://127.0.0.1:8765/safe");
        UiObject2 action=device.wait(Until.findObject(By.text("Open Shorts route")),20000);
        assertNotNull("Local SPA fixture unavailable",action);
        int before=state().transitions;
        action.click();
        blockedOutcome(before,"Chrome pushState navigation was not blocked by exact URL rules");
    }
    @Test public void test05NavigationAfterToolbarScroll() throws Exception {
        home();
        setRules("127.0.0.1/shorts");
        open("http://127.0.0.1:8765/safe?scroll=1");
        assertNotNull("Scroll fixture unavailable",device.wait(Until.findObject(By.text("Open Shorts route")),20000));
        device.swipe(device.getDisplayWidth()/2,device.getDisplayHeight()*3/4,
            device.getDisplayWidth()/2,device.getDisplayHeight()/4,20);
        SystemClock.sleep(1500);
        File dir=new File(app.getExternalFilesDir(null),"ci-evidence"); dir.mkdirs();
        device.dumpWindowHierarchy(new File(dir,"before-scroll-navigation.xml"));
        device.takeScreenshot(new File(dir,"before-scroll-navigation.png"));
        UiObject2 bar=device.findObject(By.res("com.android.chrome","url_bar"));
        try(FileWriter writer=new FileWriter(new File(dir,"scroll-address-state.txt"))) {
            writer.write("Address bar present after scroll: "+(bar!=null)+"\n");
        }
        UiObject2 action=device.findObject(By.text("Open Shorts route"));
        assertNotNull("Fixed navigation button unavailable after scroll",action);
        int before=state().transitions;
        action.click();
        blockedOutcome(before,"Navigation after toolbar scroll was not blocked");
    }
    @Test public void test06RepeatedShortsAndReturnFromHome() {
        home();
        for(int attempt=0;attempt<3;attempt++) {
            int before=state().transitions;
            open("https://m.youtube.com/shorts/wmzbgQAqjvI");
            blockedOutcome(before,"Repeated Shorts entry was not blocked: "+attempt);
            device.pressHome();
            await(()->!state().cover,3000,"Cover remained outside Chrome");
            home();
        }
    }
    @Test public void test07PreviewMasksTrackScrollAndDynamicCards() {
        home(); int before=state().transitions;
        open("http://127.0.0.1:8765/previews");
        UiObject2 card=device.wait(Until.findObject(By.desc("Shorts preview one")),20000);
        assertNotNull("Preview fixture unavailable",card);
        await(()->maskCount()>0,7000,"Shorts link had no preview mask");
        SystemClock.sleep(350);
        assertPainted(card.getVisibleBounds(),Color.rgb(18,22,30),"First thumbnail was not opaque");
        UiObject2 ordinary=device.findObject(By.text("Ordinary video with Shorts in its title"));
        assertNotNull("Ordinary fixture card unavailable",ordinary);
        assertPainted(ordinary.getVisibleBounds(),Color.GREEN,"Ordinary video was incorrectly hidden");
        UiObject2 second=null;
        for(int i=0;i<6 && second==null;i++) {
            device.swipe(device.getDisplayWidth()*4/5,device.getDisplayHeight()*3/4,
                device.getDisplayWidth()*4/5,device.getDisplayHeight()/3,30);
            SystemClock.sleep(600);
            second=visible(By.desc("Shorts preview two"));
        }
        assertNotNull("Second thumbnail unavailable after scrolling",second);
        SystemClock.sleep(500);
        assertPainted(second.getVisibleBounds(),Color.rgb(18,22,30),"Mask did not follow scroll");
        UiObject2 dynamic=visible(By.text("Add dynamic card"));
        for(int i=0;i<4 && dynamic==null;i++) {
            device.swipe(device.getDisplayWidth()*4/5,device.getDisplayHeight()*3/4,
                device.getDisplayWidth()*4/5,device.getDisplayHeight()/2,20);
            SystemClock.sleep(400); dynamic=visible(By.text("Add dynamic card"));
        }
        assertNotNull("Dynamic fixture button unavailable",dynamic); dynamic.click();
        UiObject2 added=device.wait(Until.findObject(By.text("Dynamic Shorts preview")),5000);
        if(added==null) {
            device.swipe(device.getDisplayWidth()*4/5,device.getDisplayHeight()*3/4,
                device.getDisplayWidth()*4/5,device.getDisplayHeight()/2,20);
            added=device.wait(Until.findObject(By.text("Dynamic Shorts preview")),5000);
        }
        assertNotNull("Dynamic card was not inserted",added);
        SystemClock.sleep(700);
        assertPainted(added.getVisibleBounds(),Color.rgb(18,22,30),"Dynamic thumbnail was exposed");
        assertEquals("Preview masking navigated or blocked the safe page",before,state().transitions);
        device.pressHome();
        await(()->maskCount()==0,3000,"Preview masks leaked outside Chrome");
        open("http://127.0.0.1:8765/safe");
        assertNotNull(device.wait(Until.findObject(By.text("Allowed page")),10000));
        await(()->maskCount()==0,3000,"Preview masks remained on an ordinary page");
    }
    @Test public void test08LiveYouTubePreviewIsOpaque() throws Exception {
        home(); int before=state().transitions;
        open("https://m.youtube.com/results?search_query=cat+shorts");
        List<Rect> cards=new ArrayList<>();
        for(int attempt=0;attempt<8 && cards.isEmpty();attempt++) {
            SystemClock.sleep(attempt==0?7000:1500);
            cards=liveShortsCards();
            if(cards.isEmpty()) device.swipe(device.getDisplayWidth()*4/5,device.getDisplayHeight()*3/4,
                device.getDisplayWidth()*4/5,device.getDisplayHeight()/3,25);
        }
        assertFalse("Live YouTube supplied no actual Shorts thumbnail link; cannot verify",cards.isEmpty());
        await(()->maskCount()>0,7000,"Live YouTube thumbnail was not masked");
        SystemClock.sleep(500);
        cards=liveShortsCards();
        assertFalse("Live Shorts thumbnail moved offscreen before verification",cards.isEmpty());
        await(()->{
            List<Rect> visible=liveShortsCards();
            if(visible.isEmpty()) return false;
            for(Rect r:visible) if(!painted(r,Color.rgb(18,22,30))) return false;
            return true;
        },10000,"Live YouTube thumbnail remained visible");
        assertEquals("Search results were blocked instead of masking cards",before,state().transitions);
        assertFalse("Live results had a full page cover",state().cover);
    }
    @Test public void test09FeedPagesOpenAndSafeRoutesAllowed() {
        home();
        for(String url:new String[]{"https://m.youtube.com/","https://m.youtube.com/feed/subscriptions",
            "https://www.instagram.com/","https://www.instagram.com/reels/","https://www.linkedin.com/feed/"}) {
            int before=state().transitions; open(url);
            SystemClock.sleep(4500);
            assertEquals("Feed navigation was blocked: "+url,before,state().transitions);
            assertFalse("Feed had a blocking full-screen cover: "+url,state().cover);
            device.pressHome(); await(()->feedMaskCount()==0 && !state().cover,3000,"Feed masks leaked outside Chrome");
            home();
        }
        for(String url:new String[]{"https://www.instagram.com/direct/inbox/","https://www.linkedin.com/messaging/",
            "https://www.linkedin.com/jobs/"}) {
            home(); int before=state().transitions; open(url); SystemClock.sleep(4500);
            assertEquals("Safe route was blocked: "+url,before,state().transitions);
            assertFalse("Safe route was covered: "+url,state().cover);
        }
    }
    @Test public void test10FeedMasksPreserveNavigationMenusAndSafePages() throws Exception {
        home();
        for(String site:new String[]{"YouTube","Instagram","LinkedIn"}) {
            int before=state().transitions; injectFeed(site);
            String prefix=site.equals("YouTube")?"m.youtube.com":site.equals("Instagram")?"instagram.com":"linkedin.com/feed";
            await(()->address().contains(prefix),5000,"Fixture feed address was lost");
            assertEquals("Feed caused Back/blocking navigation",before,state().transitions);
            assertFalse("Feed used the blocking cover",state().cover);
            UiObject2 post=device.wait(Until.findObject(By.text("Fixture feed post one")),5000);
            assertNotNull(post);assertPainted(post.getVisibleBounds(),Color.rgb(18,22,30),"Feed post exposed: "+site);
            assertCaptionPainted(site);
            UiObject2 search=webSearchField();assertNotNull("Fixture search field unavailable",search);
            assertPainted(corner(search.getVisibleBounds()),Color.GREEN,"Feed search input was hidden");
            UiObject2 messages=visible(By.text("Messages"));assertNotNull(messages);
            assertPainted(corner(messages.getVisibleBounds()),Color.GREEN,"Bottom navigation was hidden");
            dismissObservedChromeTip();
            feedEvidence(site,"");
            UiObject2 menu=visible(By.text("Fixture menu"));assertNotNull(menu);menu.click();
            UiObject2 panel=device.wait(Until.findObject(By.desc("Fixture options")),5000);
            if(panel==null) panel=device.findObject(By.text("Fixture menu panel"));
            assertNotNull("Feed menu did not open",panel);
            assertPainted(corner(panel.getVisibleBounds()),Color.CYAN,"Feed mask covered an open menu");
            feedEvidence(site,"-menu");
            UiObject2 close=visible(By.text("Close menu"));assertNotNull(close);close.click();
            UiObject2 add=visible(By.text("Add feed card"));assertNotNull(add);add.click();
            UiObject2 dynamic=device.wait(Until.findObject(By.text("Dynamic feed post")),5000);assertNotNull(dynamic);
            assertPainted(dynamic.getVisibleBounds(),Color.rgb(18,22,30),"New feed content exposed");
            UiObject2 second=null;
            for(int i=0;i<15 && second==null;i++) {
                // User drags are swallowed by the mask. Exercise independent page-driven
                // scrolling through an uncovered menu, as dynamic sites can still scroll.
                visible(By.text("Fixture menu")).click();
                UiObject2 scroll=device.wait(Until.findObject(By.text("Scroll feed")),5000);
                assertNotNull(scroll);scroll.click();
                visible(By.text("Close menu")).click();
                SystemClock.sleep(500);
                UiObject2 candidate=visible(By.text("Fixture feed post two"));
                if(candidate!=null) {
                    Rect bounds=candidate.getVisibleBounds();
                    if(bounds.height()>device.getDisplayHeight()/8 && bounds.top>device.getDisplayHeight()/4 &&
                        bounds.bottom<device.getDisplayHeight()*9/10) second=candidate;
                }
            }
            assertNotNull("Second feed post unavailable inside content area",second);
            feedEvidence(site,"-scrolled");
            assertPainted(corner(second.getVisibleBounds()),Color.rgb(18,22,30),"Feed contents exposed after scroll");
            messages=visible(By.text("Messages"));assertNotNull(messages);messages.click();
            UiObject2 safe=device.wait(Until.findObject(By.text("Fixture safe destination")),7000);assertNotNull(safe);
            await(()->feedMaskCount()==0,5000,"Feed mask remained on a safe destination");
            assertPainted(corner(safe.getVisibleBounds()),Color.GREEN,"Safe destination was hidden");
            feedEvidence(site,"-safe");
            assertEquals("Menu or messages caused a block",before,state().transitions);
        }
        injectFeed("YouTube"); device.pressHome();
        await(()->feedMaskCount()==0,3000,"Feed mask remained outside Chrome");
    }
    @Test public void test11LiveYouTubeFeedStaysOpenWithSearchAvailable() throws Exception {
        home();int before=state().transitions;
        open("https://m.youtube.com/");
        await(()->feedMaskCount()>0,20000,"Live YouTube home feed was not hidden");
        assertEquals("Live home was blocked instead of opened",before,state().transitions);
        assertFalse("Live home used a full blocking cover",state().cover);
        assertFalse("Live home navigated back to search",address().contains("/results"));
        UiObject2 search=device.wait(Until.findObject(By.desc(Pattern.compile("(?i)(Search YouTube|Search|Поиск|Поиск на YouTube)"))),10000);
        assertNotNull("Live YouTube search control unavailable",search);
        feedEvidence("YouTube","-live");search.click();
        await(()->webSearchField()!=null,7000,"YouTube web search field did not open");
        UiObject2 input=webSearchField();assertNotNull(input);
        input.setText("ordinary video");device.pressEnter();
        await(()->address().contains("/results") && feedMaskCount()==0,12000,"Search did not leave the hidden feed");
        assertEquals("Search was blocked after opening the feed",before,state().transitions);
    }
    @Test public void test12FeedLoginFormsStayVisible() throws Exception {
        home();
        for(String site:new String[]{"Instagram","LinkedIn"}) {
            int before=state().transitions;injectFeed(site,true);
            UiObject2 form=device.wait(Until.findObject(By.text("Fixture sign-in")),5000);assertNotNull(form);
            await(()->feedMaskCount()==0,5000,"Feed mask concealed a sign-in form");
            assertPainted(corner(form.getVisibleBounds()),Color.GREEN,"Sign-in heading was hidden");
            assertTrue("Password field unavailable",visiblePassword());
            assertEquals("Login page was blocked",before,state().transitions);
            feedEvidence(site,"-login");
        }
    }
    private void assertNoExposedFeed(UiAutomation automation,String label) throws Exception {
        Bitmap shot=automation.takeScreenshot();assertNotNull("No scroll screenshot",shot);
        try {
            int exposed=0;
            for(int y=shot.getHeight()/4;y<shot.getHeight()*4/5;y+=2)
                for(int x=shot.getWidth()/5;x<shot.getWidth()*4/5;x+=2) {
                    int c=shot.getPixel(x,y);
                    if(Color.red(c)>240 && Color.green(c)<15 && Color.blue(c)>240) exposed++;
                }
            File dir=new File(app.getExternalFilesDir(null),"ci-evidence");dir.mkdirs();
            try(FileOutputStream out=new FileOutputStream(new File(dir,"continuous-"+label+".png"))) {
                shot.compress(Bitmap.CompressFormat.PNG,100,out);
            }
            assertEquals("Feed pixels exposed during gesture: "+label,0,exposed);
        } finally { shot.recycle(); }
    }
    private void touch(UiAutomation automation,long down,int action,float x,float y) {
        MotionEvent e=MotionEvent.obtain(down,SystemClock.uptimeMillis(),action,x,y,0);
        e.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        try { assertTrue("Touch injection failed",automation.injectInputEvent(e,true)); }
        finally { e.recycle(); }
    }
    @Test public void test13FeedSwallowsTapsAndDragsWithShortLandmark() throws Exception {
        home();UiAutomation automation=InstrumentationRegistry.getInstrumentation()
            .getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
        for(String site:new String[]{"YouTube","Instagram","LinkedIn"}) {
            injectFeed(site,false,true);dismissObservedChromeTip();
            assertNoExposedFeed(automation,site+"-before");
            UiObject2 post=visible(By.text("Fixture feed post one"));assertNotNull(post);
            Rect first=new Rect(post.getVisibleBounds());
            device.click(first.centerX(),first.centerY());
            SystemClock.sleep(200);
            assertNotNull("Tap reached the covered feed",visible(By.text("Fixture feed taps: 0")));
            int w=device.getDisplayWidth(),h=device.getDisplayHeight();
            for(int gesture=0;gesture<3;gesture++) {
                long down=SystemClock.uptimeMillis();float x=w*0.7f,from=h*0.72f,to=h*0.35f;
                if(gesture==1) { float swap=from;from=to;to=swap; }
                touch(automation,down,MotionEvent.ACTION_DOWN,x,from);
                try {
                    for(int move=1;move<=12;move++) {
                        touch(automation,down,MotionEvent.ACTION_MOVE,x,from+(to-from)*move/12);
                        if(move%4==0) assertNoExposedFeed(automation,site+"-"+gesture+"-"+move);
                        SystemClock.sleep(25);
                    }
                } finally { touch(automation,down,MotionEvent.ACTION_UP,x,to); }
                assertNoExposedFeed(automation,site+"-after-"+gesture);
            }
            post=visible(By.text("Fixture feed post one"));assertNotNull("Drag scrolled the covered feed",post);
            assertEquals("Underlying page moved under the mask",first,post.getVisibleBounds());
            assertNotNull("Covered gestures reached feed content",visible(By.text("Fixture feed taps: 0")));
            assertFalse("Mask caused a blocking navigation",state().cover);
            feedEvidence(site,"-touch-guard");
        }
    }
    @Test public void test14LinkedInOwnNavigationWithoutPageMessagesButton() throws Exception {
        home();
        for(String action:new String[]{"Сообщения","Вакансии"}) {
            injectFeed("LinkedIn",false,true);dismissObservedChromeTip();
            assertNull("Fixture must omit its own Messages button",visible(By.text("Messages")));
            UiObject2 button=device.wait(Until.findObject(By.text(action)),5000);
            assertNotNull("NoShorts navigation unavailable: "+action,button);
            assertEquals("Expected a native mask button",BLOCKER,button.getApplicationPackage());
            button.click();
            await(()->feedMaskCount()==0 && address().contains("linkedin.com"),15000,
                "Native safe navigation left feed masked: "+action);
            assertEquals("Native safe navigation left Chrome","com.android.chrome",device.getCurrentPackageName());
            assertFalse("Native navigation was blocked",state().cover);
            feedEvidence("LinkedIn",action.equals("Сообщения")?"-own-messages":"-own-jobs");
        }
    }
}
