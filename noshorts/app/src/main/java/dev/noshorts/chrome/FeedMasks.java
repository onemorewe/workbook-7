package dev.noshorts.chrome;

import android.content.Context;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.TextView;
import android.widget.Button;
import android.widget.LinearLayout;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Consumer;

/** Hides a feed's content without navigating away or covering the browser toolbar. */
final class FeedMasks {
    private static final String ROLE="AccessibilityNodeInfo.chromeRole";
    private final Context context;
    private final WindowManager windows;
    private final List<MaskPanel> views=new ArrayList<>();
    private final Consumer<String> openSafe;
    private List<Rect> current=new ArrayList<>();
    private String activeSite,caption="";
    private final Map<String,Integer> visits=new HashMap<>();
    private int remaining;

    FeedMasks(Context context,Consumer<String> openSafe) {
        this.context=context;
        this.openSafe=openSafe;
        windows=(WindowManager)context.getSystemService(Context.WINDOW_SERVICE);
    }
    int count() { return views.size(); }
    private String phrase(String site) {
        String[] phrases;
        switch(site) {
            case "YouTube": phrases=new String[]{
                "Сосать, Сундар Пичаи.\nМой мозг сегодня не абузишь.",
                "Сундар Пичаи, лента идёт нахуй.\nМоё внимание остаётся у меня.",
                "Сосать, Сундар Пичаи.\nЕщё один ролик? Хуй тебе."}; break;
            case "Instagram": phrases=new String[]{
                "Сосать, Марк Цукерберг.\nМой мозг не твоя рекламная площадка.",
                "Марк Цукерберг, Reels идут нахуй.\nСегодня я живу свою жизнь.",
                "Сосать, Марк Цукерберг.\nБесконечная лента сегодня без меня."}; break;
            default: phrases=new String[]{
                "Сосать, Сатья Наделла.\nМой ёбаный мозг ты сегодня не абузишь.",
                "Сатья Наделла, лента идёт нахуй.\nЯ зашёл по делу.",
                "Сосать, Сатья Наделла.\nМоё внимание тебе не принадлежит."};
        }
        int visit=visits.getOrDefault(site,0); visits.put(site,visit+1);
        return phrases[visit%phrases.length];
    }
    void update(AccessibilityNodeInfo root,String site) {
        if(site==null) { clear(); return; }
        boolean changed=!site.equals(activeSite);
        if(changed) { activeSite=site; caption=phrase(site); }
        remaining=2000;
        List<Rect> regions=new ArrayList<>();
        findWebViews(root,regions,0);
        if(!changed && regions.equals(current)) return;
        int largest=-1; long area=0;
        for(int i=0;i<regions.size();i++) {
            Rect r=regions.get(i); long a=(long)r.width()*r.height();
            if(a>area) { area=a; largest=i; }
        }
        for(int i=0;i<regions.size();i++) {
            Rect r=regions.get(i);
            MaskPanel view;
            if(i<views.size()) view=views.get(i);
            else {
                view=new MaskPanel();
                view.setBackgroundColor(PreviewMasks.COLOR);
                view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
                views.add(view); windows.addView(view,params(r));
            }
            view.display(site,i==largest && r.height()>180);
            windows.updateViewLayout(view,params(r));
        }
        while(views.size()>regions.size()) removeLast();
        current=regions;
    }
    private final class MaskPanel extends LinearLayout {
        final TextView message;
        final LinearLayout actions;
        String buttonsFor;
        MaskPanel() {
            super(context);setOrientation(VERTICAL);
            // Masked feed content has no useful touch target. Consume taps and drags,
            // while NOT_TOUCH_MODAL leaves the uncovered navigation windows usable.
            setOnTouchListener((v,event)->true);
            message=new TextView(context);message.setTextColor(0xfff4f5f7);message.setTextSize(20);
            message.setGravity(Gravity.CENTER);
            int pad=(int)(24*context.getResources().getDisplayMetrics().density);
            message.setPadding(pad,pad,pad,pad);
            addView(message,new LinearLayout.LayoutParams(-1,0,1));
            actions=new LinearLayout(context);actions.setPadding(pad/2,0,pad/2,pad/2);
            addView(actions,new LinearLayout.LayoutParams(-1,-2));
        }
        void display(String site,boolean primary) {
            message.setText(primary?caption:"");
            String next=primary?site:"";
            if(!next.equals(buttonsFor)) {
                buttonsFor=next;actions.removeAllViews();
                if(next.equals("LinkedIn")) {
                    addAction("Сообщения","https://www.linkedin.com/messaging/");
                    addAction("Вакансии","https://www.linkedin.com/jobs/");
                } else if(next.equals("Instagram")) addAction("Сообщения","https://www.instagram.com/direct/inbox/");
            }
            actions.setVisibility(actions.getChildCount()==0?View.GONE:View.VISIBLE);
        }
        private void addAction(String title,String url) {
            Button button=new Button(context);button.setText(title);button.setAllCaps(false);
            button.setTextSize(14);button.setOnClickListener(v->openSafe.accept(url));
            actions.addView(button,new LinearLayout.LayoutParams(0,-2,1));
        }
    }
    private WindowManager.LayoutParams params(Rect r) {
        WindowManager.LayoutParams p=new WindowManager.LayoutParams(r.width(),r.height(),
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE|WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL|
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN|WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.OPAQUE);
        p.gravity=Gravity.TOP|Gravity.LEFT; p.x=r.left; p.y=r.top;
        p.setTitle("NoShorts feed mask"); return p;
    }
    private void findWebViews(AccessibilityNodeInfo node,List<Rect> result,int depth) {
        if(node==null || depth>60 || --remaining<0) return;
        if("android.webkit.WebView".contentEquals(node.getClassName()==null?"":node.getClassName())) {
            Rect viewport=new Rect(); node.getBoundsInScreen(viewport);
            if(viewport.isEmpty()) return;
            Layout layout=new Layout(viewport);
            inspect(node,layout,0,false);
            // Never conceal a sign-in form. Feed masking resumes after login navigation.
            if(layout.password) return;
            List<Rect> regions=new ArrayList<>();
            // Feed/main landmarks can describe only mounted cards and move/shrink
            // during scrolling. Cover the viewport, not these content rectangles.
            regions.add(new Rect(viewport));
            for(Rect hole:layout.controls) regions=subtract(regions,hole);
            for(Rect r:regions) if(r.width()>8 && r.height()>8) result.add(r);
            return;
        }
        for(int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo child=node.getChild(i);
            try { findWebViews(child,result,depth+1); }
            finally { if(child!=null) child.recycle(); }
        }
    }
    private static final class Layout {
        final Rect viewport;
        Rect main,feed;
        boolean password;
        final List<Rect> controls=new ArrayList<>();
        Layout(Rect viewport) { this.viewport=viewport; }
    }
    private void inspect(AccessibilityNodeInfo node,Layout layout,int depth,boolean insidePost) {
        if(node==null || depth>60 || --remaining<0) return;
        String role=string(node.getExtras().getCharSequence(ROLE));
        Rect r=new Rect(); node.getBoundsInScreen(r);
        boolean visible=!r.isEmpty() && r.intersect(layout.viewport);
        insidePost|=role.equals("article");
        if(visible) {
            layout.password|=node.isPassword();
            if(role.equals("feed")) layout.feed=larger(layout.feed,r);
            if(role.equals("main")) layout.main=larger(layout.main,r);
            boolean popup=role.equals("dialog") || role.equals("alertDialog") ||
                role.equals("menu") || role.equals("listBox");
            boolean nav=!insidePost && (role.equals("navigation") || role.equals("toolbar") ||
                role.equals("search") || ((role.equals("header") || role.equals("banner")) &&
                r.top<layout.viewport.top+layout.viewport.height()/3));
            // Full-page generic headers are not navigation. Sidebar navigation is allowed.
            if(nav && (r.height()>layout.viewport.height()/2 && r.width()>layout.viewport.width()/2)) nav=false;
            boolean input=node.isEditable() || role.equals("searchBox") || role.equals("textField");
            if(popup || nav || input) layout.controls.add(new Rect(r));
            String label=(string(node.getContentDescription())+" "+string(node.getText())).trim().toLowerCase(Locale.ROOT);
            if(!insidePost && isNavigationLabel(label) &&
                (r.top>=layout.viewport.bottom-layout.viewport.height()/5 ||
                r.bottom<=layout.viewport.top+layout.viewport.height()/5)) {
                // Preserve a whole fixed row, including icon padding and the gaps between tabs.
                Rect row=new Rect(layout.viewport.left,Math.max(layout.viewport.top,r.top-4),
                    layout.viewport.right,Math.min(layout.viewport.bottom,r.bottom+4));
                layout.controls.add(row);
            }
        }
        for(int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo child=node.getChild(i);
            try { inspect(child,layout,depth+1,insidePost); }
            finally { if(child!=null) child.recycle(); }
        }
    }
    private static String string(CharSequence s) { return s==null?"":s.toString(); }
    private static boolean isNavigationLabel(String value) {
        return value.matches("home|youtube home|instagram|linkedin|shorts|subscriptions|you|search|search and explore|explore|reels|messages|messaging|direct|notifications|jobs|my network|me|profile|your profile|my profile|profile picture|create|главная|подписки|вы|поиск|сообщения|уведомления|вакансии|профиль|ваш профиль|моя сеть|обзор");
    }
    private static Rect larger(Rect a,Rect b) {
        return a==null || (long)b.width()*b.height()>(long)a.width()*a.height()?new Rect(b):a;
    }
    private static List<Rect> subtract(List<Rect> regions,Rect hole) {
        List<Rect> out=new ArrayList<>();
        for(Rect r:regions) {
            Rect cut=new Rect(r);
            if(!cut.intersect(hole)) { out.add(r); continue; }
            if(r.top<cut.top) out.add(new Rect(r.left,r.top,r.right,cut.top));
            if(cut.bottom<r.bottom) out.add(new Rect(r.left,cut.bottom,r.right,r.bottom));
            if(r.left<cut.left) out.add(new Rect(r.left,cut.top,cut.left,cut.bottom));
            if(cut.right<r.right) out.add(new Rect(cut.right,cut.top,r.right,cut.bottom));
        }
        return out;
    }
    private void removeLast() {
        MaskPanel view=views.remove(views.size()-1);
        try { windows.removeView(view); } catch(RuntimeException ignored) { }
    }
    void clear() {
        while(!views.isEmpty()) removeLast();
        current=new ArrayList<>(); activeSite=null;
    }
}
