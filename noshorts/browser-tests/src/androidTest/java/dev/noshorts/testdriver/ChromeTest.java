package dev.noshorts.testdriver;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Context;
import android.content.ComponentName;
import android.content.Intent;
import android.net.Uri;
import android.os.SystemClock;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.uiautomator.*;
import org.junit.*;
import org.junit.runner.RunWith;
import org.junit.runners.MethodSorters;
import java.io.File;
import java.io.FileWriter;
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
        // Gradle uninstalls this driver after instrumentation; keep evidence outside its data.
        device.executeShellCommand("mkdir -p /sdcard/Download/noshorts-ci");
        device.executeShellCommand("cp -R "+dir.getAbsolutePath()+"/. /sdcard/Download/noshorts-ci/");
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
        open("https://m.youtube.com/");
        long deadline=SystemClock.uptimeMillis()+30000;
        while(SystemClock.uptimeMillis()<deadline) {
            UiObject2 safe=device.findObject(By.text("Открыть обычный YouTube"));
            if(safe!=null) safe.click();
            UiObject2 onboarding=device.findObject(By.res("com.android.chrome","signin_fre_dismiss_button"));
            if(onboarding==null) onboarding=device.findObject(By.text(Pattern.compile("(?i)(stay signed out|continue without an account|use without an account|accept & continue|no thanks|not now|got it|skip)")));
            if(onboarding!=null) onboarding.click();
            if(device.hasObject(By.res("com.android.chrome","url_bar")) && onboarding==null && !state().cover) break;
            SystemClock.sleep(300);
        }
        assertTrue("Chrome address bar unavailable",device.hasObject(By.res("com.android.chrome","url_bar")));
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
}
