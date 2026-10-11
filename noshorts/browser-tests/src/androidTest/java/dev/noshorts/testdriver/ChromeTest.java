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
        Matcher m=Pattern.compile("NoShorts connected=(true|false) transitions=(\\d+) cover=(true|false)").matcher(serviceDump());
        if(!m.find()) return new ServiceState(false,-1,false);
        return new ServiceState(Boolean.parseBoolean(m.group(1)),Integer.parseInt(m.group(2)),Boolean.parseBoolean(m.group(3)));
    }
    private int maskCount() {
        Matcher m=Pattern.compile("masks=(\\d+)").matcher(serviceDump());
        return m.find()?Integer.parseInt(m.group(1)):-1;
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
    @Test public void test09FeedPagesBlockedAndSafeRoutesAllowed() {
        home();
        for(String url:new String[]{"https://m.youtube.com/","https://m.youtube.com/feed/subscriptions",
            "https://www.instagram.com/","https://www.instagram.com/reels/","https://www.linkedin.com/feed/"}) {
            int before=state().transitions; open(url);
            await(()->state().transitions>before,12000,"Feed route was not blocked: "+url);
            device.pressHome(); await(()->!state().cover,3000,"Feed cover leaked outside Chrome");
            home();
        }
        for(String url:new String[]{"https://www.instagram.com/direct/inbox/","https://www.linkedin.com/messaging/",
            "https://www.linkedin.com/jobs/"}) {
            home(); int before=state().transitions; open(url); SystemClock.sleep(4500);
            assertEquals("Safe route was blocked: "+url,before,state().transitions);
            assertFalse("Safe route was covered: "+url,state().cover);
        }
    }
}
