package dev.noshorts.chrome;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityWindowInfo;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.List;
import java.io.FileDescriptor;
import java.io.PrintWriter;
import dev.noshorts.core.Guard;
import dev.noshorts.core.UrlRules;
import dev.noshorts.core.ChromeAddress;

/** Blocks navigation by native address; hides previews by Chrome's exact link destinations. */
public final class ShortsService extends AccessibilityService implements SharedPreferences.OnSharedPreferenceChangeListener {
    public static volatile boolean connected;
    public static volatile int blockedTransitions;
    public static volatile boolean coverVisible;
    private static final String CHROME="com.android.chrome";
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Guard guard=new Guard();
    private UrlRules rules=new UrlRules("");
    private View cover;
    private boolean queued;
    private long lastBack;
    private SharedPreferences preferences;
    private PreviewMasks previews;
    private boolean youtubePage;
    private long pendingBlockUntil;
    private final Runnable poll=()->{queued=false; scan();};

    @Override public void onServiceConnected() {
        connected=true;
        previews=new PreviewMasks(this);
        preferences=getSharedPreferences("rules",MODE_PRIVATE);
        preferences.registerOnSharedPreferenceChangeListener(this);
        loadRules(); queue(0);
    }
    @Override public void onSharedPreferenceChanged(SharedPreferences p,String key) { loadRules(); queue(0); }
    private void loadRules() {
        try { rules=new UrlRules(preferences.getString("extra","")); }
        catch(IllegalArgumentException ex) { rules=new UrlRules(""); }
    }
    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        if(event!=null && CHROME.contentEquals(event.getPackageName()==null ? "" : event.getPackageName())) {
            if(event.getEventType()==AccessibilityEvent.TYPE_VIEW_CLICKED && blockedClick(event))
                pendingBlockUntil=SystemClock.elapsedRealtime()+900;
            queue(0);
        }
    }
    private boolean blockedClick(AccessibilityEvent event) {
        AccessibilityNodeInfo node=event.getSource();
        try {
            for(int depth=0;node!=null && depth<4;depth++) {
                if("android.webkit.WebView".contentEquals(node.getClassName()==null?"":node.getClassName())) break;
                CharSequence target=node.getExtras().getCharSequence("AccessibilityNodeInfo.targetUrl");
                if(target!=null && rules.evaluate(target.toString())==UrlRules.Verdict.BLOCK) return true;
                if(PreviewMasks.isShortsAction(node,youtubePage)) return true;
                AccessibilityNodeInfo parent=node.getParent(); node.recycle(); node=parent;
            }
            return false;
        } finally { if(node!=null) node.recycle(); }
    }
    private void queue(long delay) {
        if(queued && delay==0) { handler.removeCallbacks(poll); queued=false; }
        if(!queued) { queued=true; handler.postDelayed(poll,delay); }
    }
    private AccessibilityNodeInfo chromeRoot() {
        // A non-focusable accessibility overlay must not become the inspected application.
        for(AccessibilityWindowInfo w:getWindows()) {
            if(w.getType()!=AccessibilityWindowInfo.TYPE_APPLICATION || (!w.isActive() && !w.isFocused())) continue;
            AccessibilityNodeInfo root=w.getRoot();
            if(root==null) continue;
            if(CHROME.contentEquals(root.getPackageName()==null ? "" : root.getPackageName())) return root;
            root.recycle();
            return null; // Never inspect another application's text.
        }
        AccessibilityNodeInfo root=getRootInActiveWindow();
        if(root!=null && CHROME.contentEquals(root.getPackageName()==null ? "" : root.getPackageName())) return root;
        if(root!=null) root.recycle();
        return null;
    }
    private void scan() {
        AccessibilityNodeInfo root=null;
        try {
            root=chromeRoot();
            if(root==null) { removeCover(); previews.clear(); queue(250); return; }
            UrlRules.Verdict verdict=addressVerdict(root);
            // A click is a navigation request. Keep it covered while Chrome still reports
            // the previous allowed page; the real URL or Guard takes over after this interval.
            if(SystemClock.elapsedRealtime()<pendingBlockUntil) verdict=UrlRules.Verdict.BLOCK;
            boolean wasBlocked=guard.isBlocked();
            boolean blocked=guard.observe(verdict);
            if(blocked && !wasBlocked) blockedTransitions++;
            if(blocked) {
                previews.clear();
                showCover();
                // One Back request on entry, no cooldown that turns detection off.
                // If Back does not navigate, the cover remains and the user can open safe home.
                long now=SystemClock.elapsedRealtime();
                if(!wasBlocked && now-lastBack>1000) { lastBack=now; performGlobalAction(GLOBAL_ACTION_BACK); }
            } else {
                removeCover();
                previews.update(root,youtubePage);
            }
            queue(previews.count()>0?120:250);
        } catch(RuntimeException ex) {
            // Tree/window can disappear mid-read; preserve the guard decision and retry.
            queue(250);
        } finally { if(root!=null) root.recycle(); }
    }
    private UrlRules.Verdict addressVerdict(AccessibilityNodeInfo root) {
        List<AccessibilityNodeInfo> nodes=root.findAccessibilityNodeInfosByViewId(CHROME+":id/url_bar");
        try {
            for(AccessibilityNodeInfo n:nodes) {
                // Don't block while someone is typing a not-yet-opened URL.
                if(n.isEditable() && n.isFocused()) continue;
                CharSequence text=n.getText();
                UrlRules.Verdict verdict=rules.evaluate(ChromeAddress.fromNodeText(text==null ? null : text.toString()));
                if(verdict!=UrlRules.Verdict.UNKNOWN) {
                    youtubePage=UrlRules.isYouTube(ChromeAddress.fromNodeText(text==null?null:text.toString()));
                    return verdict;
                }
            }
            return documentVerdict(root,0);
        } finally { for(AccessibilityNodeInfo n:nodes) n.recycle(); }
    }
    private UrlRules.Verdict documentVerdict(AccessibilityNodeInfo node,int depth) {
        if(node==null || depth>30) return UrlRules.Verdict.UNKNOWN;
        // Only the document WebView's own URL; a link on the page is never navigation evidence.
        if("android.webkit.WebView".contentEquals(node.getClassName()==null?"":node.getClassName())) {
            for(String key:new String[]{"AccessibilityNodeInfo.targetUrl","url"}) {
                CharSequence text=node.getExtras().getCharSequence(key);
                UrlRules.Verdict v=rules.evaluate(text==null?null:text.toString());
                if(v!=UrlRules.Verdict.UNKNOWN) { youtubePage=UrlRules.isYouTube(text.toString()); return v; }
            }
            return UrlRules.Verdict.UNKNOWN;
        }
        for(int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo child=node.getChild(i);
            try {
                UrlRules.Verdict v=documentVerdict(child,depth+1);
                if(v!=UrlRules.Verdict.UNKNOWN) return v;
            } finally { if(child!=null) child.recycle(); }
        }
        return UrlRules.Verdict.UNKNOWN;
    }
    private void showCover() {
        if(cover!=null) return;
        LinearLayout panel=new LinearLayout(this); panel.setId(R.id.blocked_cover); panel.setOrientation(LinearLayout.VERTICAL); panel.setGravity(Gravity.CENTER);
        panel.setPadding(40,40,40,40); panel.setBackgroundColor(Color.rgb(18,22,30));
        TextView title=new TextView(this); title.setText("Этот раздел заблокирован"); title.setTextColor(Color.WHITE); title.setTextSize(26); panel.addView(title);
        TextView details=new TextView(this); details.setText("Ленты и короткие ролики закрыты.\nПоиск, обычные видео, сообщения и вакансии доступны."); details.setTextColor(Color.LTGRAY); details.setTextSize(16); details.setPadding(0,25,0,25); panel.addView(details);
        Button safe=new Button(this); safe.setText("Поиск и сообщения"); safe.setAllCaps(false);
        safe.setOnClickListener(v->{
            try {
                startActivity(new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                guard.openSafeHome(); removeCover(); queue(0);
            } catch(RuntimeException ex) { performGlobalAction(GLOBAL_ACTION_HOME); }
        }); panel.addView(safe);
        Button home=new Button(this); home.setText("На экран телефона"); home.setAllCaps(false);
        home.setOnClickListener(v->{ performGlobalAction(GLOBAL_ACTION_HOME); removeCover(); queue(0); }); panel.addView(home);
        WindowManager.LayoutParams p=new WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,android.graphics.PixelFormat.OPAQUE);
        p.gravity=Gravity.TOP|Gravity.START;
        ((WindowManager)getSystemService(WINDOW_SERVICE)).addView(panel,p); cover=panel; coverVisible=true;
    }
    private void removeCover() {
        if(cover==null) return;
        try { ((WindowManager)getSystemService(WINDOW_SERVICE)).removeView(cover); }
        catch(RuntimeException ignored) { }
        cover=null;
        coverVisible=false;
    }
    @Override public void onInterrupt() { removeCover(); if(previews!=null) previews.clear(); }
    @Override protected void dump(FileDescriptor fd, PrintWriter writer, String[] args) {
        // System shell diagnostics only; no URL, page text or browsing history is exposed.
        writer.println("NoShorts connected="+connected+" transitions="+blockedTransitions+" cover="+coverVisible+
            " masks="+(previews==null?0:previews.count()));
    }
    @Override public void onDestroy() {
        connected=false; handler.removeCallbacksAndMessages(null); queued=false; removeCover();
        if(previews!=null) previews.clear();
        if(preferences!=null) preferences.unregisterOnSharedPreferenceChangeListener(this);
        super.onDestroy();
    }
}
