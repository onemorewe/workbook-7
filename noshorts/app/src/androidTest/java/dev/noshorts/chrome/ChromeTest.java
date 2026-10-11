package dev.noshorts.chrome;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.content.Context;
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
import java.util.function.BooleanSupplier;
import java.util.regex.Pattern;
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
        device.executeShellCommand("settings put secure enabled_accessibility_services dev.noshorts.chrome/dev.noshorts.chrome.ShortsService");
        device.executeShellCommand("settings put secure accessibility_enabled 1");
        await(()->ShortsService.connected,15000,"Accessibility service did not connect");
        app.getSharedPreferences("rules",Context.MODE_PRIVATE).edit().putString("extra","").commit();
    }
    @After public void evidence() throws Exception {
        File dir=new File(app.getExternalFilesDir(null),"ci-evidence"); dir.mkdirs();
        String suffix=Long.toString(System.currentTimeMillis());
        device.dumpWindowHierarchy(new File(dir,"hierarchy-"+suffix+".xml"));
        device.takeScreenshot(new File(dir,"screen-"+suffix+".png"));
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
            "; connected="+ShortsService.connected+"; transitions="+ShortsService.blockedTransitions+"; cover="+ShortsService.coverVisible);
    }
    private void home() {
        open("https://m.youtube.com/");
        long deadline=SystemClock.uptimeMillis()+30000;
        while(SystemClock.uptimeMillis()<deadline) {
            UiObject2 safe=device.findObject(By.text("Открыть обычный YouTube"));
            if(safe!=null) safe.click();
            UiObject2 onboarding=device.findObject(By.text(Pattern.compile("(?i)(use without an account|accept & continue|no thanks|got it|skip)")));
            if(onboarding!=null) onboarding.click();
            if(device.hasObject(By.res("com.android.chrome","url_bar")) && onboarding==null && !ShortsService.coverVisible) break;
            SystemClock.sleep(300);
        }
        assertTrue("Chrome address bar unavailable",device.hasObject(By.res("com.android.chrome","url_bar")));
    }
    private void blockedOutcome(int before,String message) {
        await(()->ShortsService.blockedTransitions>before,20000,message);
        await(()->{
            if(device.hasObject(By.text("Этот раздел заблокирован"))) return true;
            UiObject2 bar=device.findObject(By.res("com.android.chrome","url_bar"));
            return bar==null || !bar.getText().contains("/shorts");
        },7000,"Shorts still exposed after detection");
    }
    @Test public void test01OrdinaryYouTubeIsAllowed() {
        home(); int before=ShortsService.blockedTransitions;
        open("https://m.youtube.com/results?search_query=shorts");
        SystemClock.sleep(5000);
        assertEquals("Search was falsely blocked",before,ShortsService.blockedTransitions);
        assertFalse("Search is covered",ShortsService.coverVisible);
        open("https://m.youtube.com/watch?v=wmzbgQAqjvI");
        SystemClock.sleep(5000);
        assertEquals("Ordinary player was falsely blocked",before,ShortsService.blockedTransitions);
        assertFalse("Ordinary player is covered",ShortsService.coverVisible);
    }
    @Test public void test02DirectShortsIsBlocked() {
        home(); int before=ShortsService.blockedTransitions;
        open("https://m.youtube.com/shorts/wmzbgQAqjvI");
        blockedOutcome(before,"Direct YouTube Shorts was not detected");
        device.pressHome();
        await(()->!ShortsService.coverVisible,3000,"Cover leaked outside Chrome");
    }
    @Test public void test03YouTubeNavigationIsBlocked() {
        home();
        UiObject2 shorts=device.wait(Until.findObject(By.text("Shorts")),25000);
        if(shorts==null) shorts=device.findObject(By.desc("Shorts"));
        assertNotNull("Live YouTube Shorts entry was not available; this test must not be silently skipped",shorts);
        int before=ShortsService.blockedTransitions;
        shorts.click();
        blockedOutcome(before,"YouTube in-page Shorts navigation was not blocked");
    }
    @Test public void test04ChromeHistoryApiAndCustomPath() {
        home();
        app.getSharedPreferences("rules",Context.MODE_PRIVATE).edit().putString("extra","127.0.0.1/shorts").commit();
        open("http://127.0.0.1:8765/safe");
        UiObject2 action=device.wait(Until.findObject(By.text("Open Shorts route")),20000);
        assertNotNull("Local SPA fixture unavailable",action);
        int before=ShortsService.blockedTransitions;
        action.click();
        blockedOutcome(before,"Chrome pushState navigation was not blocked by exact URL rules");
    }
}
