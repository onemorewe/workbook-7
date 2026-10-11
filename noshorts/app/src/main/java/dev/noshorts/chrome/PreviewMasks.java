package dev.noshorts.chrome;

import android.content.Context;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import java.util.ArrayList;
import java.util.List;
import dev.noshorts.core.UrlRules;

/** Covers actual Shorts link regions. A word in page text is never a match. */
final class PreviewMasks {
    static final int COLOR=Color.rgb(18,22,30);
    private static final String TARGET="AccessibilityNodeInfo.targetUrl";
    private static final UrlRules SHORTS=new UrlRules("");
    private final Context context;
    private final WindowManager windows;
    private final List<View> views=new ArrayList<>();
    private List<Rect> current=new ArrayList<>();
    private int remaining;

    PreviewMasks(Context context) {
        this.context=context;
        windows=(WindowManager)context.getSystemService(Context.WINDOW_SERVICE);
    }
    int count() { return views.size(); }
    void update(AccessibilityNodeInfo root) {
        remaining=1400;
        List<Rect> regions=new ArrayList<>();
        findWebViews(root,regions,0);
        if(regions.equals(current)) return;
        // Reuse existing windows so a new scan does not uncover their old contents.
        for(int i=0;i<regions.size();i++) {
            Rect r=regions.get(i);
            WindowManager.LayoutParams p=params(r);
            if(i<views.size()) windows.updateViewLayout(views.get(i),p);
            else {
                View view=new View(context);
                view.setBackgroundColor(COLOR);
                view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
                windows.addView(view,p);
                views.add(view);
            }
        }
        while(views.size()>regions.size()) removeLast();
        current=regions;
    }
    private WindowManager.LayoutParams params(Rect r) {
        WindowManager.LayoutParams p=new WindowManager.LayoutParams(r.width(),r.height(),
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE|WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE|
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN|WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.OPAQUE);
        p.gravity=Gravity.TOP|Gravity.LEFT;
        p.x=r.left; p.y=r.top;
        p.setTitle("NoShorts preview mask");
        return p;
    }
    private void findWebViews(AccessibilityNodeInfo node,List<Rect> result,int depth) {
        if(node==null || depth>60 || --remaining<0) return;
        if("android.webkit.WebView".contentEquals(node.getClassName()==null?"":node.getClassName())) {
            Rect viewport=new Rect(); node.getBoundsInScreen(viewport);
            if(!viewport.isEmpty()) {
                Summary s=inspect(node,viewport,0);
                for(Rect r:s.regions) addRegion(result,r);
            }
            return;
        }
        for(int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo child=node.getChild(i);
            try { findWebViews(child,result,depth+1); }
            finally { if(child!=null) child.recycle(); }
        }
    }
    private static final class Summary {
        boolean shorts,other,incomplete;
        int distance=1000;
        final List<Rect> regions=new ArrayList<>();
    }
    private Summary inspect(AccessibilityNodeInfo node,Rect viewport,int depth) {
        Summary s=new Summary();
        if(node==null || depth>60 || --remaining<0) { s.incomplete=true; return s; }
        CharSequence target=node.getExtras().getCharSequence(TARGET);
        if(target!=null && target.length()>0) {
            s.shorts=SHORTS.evaluate(target.toString())==UrlRules.Verdict.BLOCK;
            s.other=!s.shorts;
            if(s.shorts) s.distance=0;
        }
        for(int i=0;i<node.getChildCount();i++) {
            AccessibilityNodeInfo child=node.getChild(i);
            Summary c;
            try { c=inspect(child,viewport,depth+1); }
            finally { if(child!=null) child.recycle(); }
            s.shorts|=c.shorts; s.other|=c.other; s.incomplete|=c.incomplete;
            s.distance=Math.min(s.distance,c.distance+1);
            s.regions.addAll(c.regions);
        }
        Rect bounds=new Rect(); node.getBoundsInScreen(bounds);
        // Promote up to two containers around a link to include the whole thumbnail/card.
        // Never promote a partial traversal or a mixed shelf containing ordinary links.
        boolean exact=s.shorts && target!=null && SHORTS.evaluate(target.toString())==UrlRules.Verdict.BLOCK;
        boolean card=s.shorts && !s.other && !s.incomplete && s.distance<=2 && depth>0 &&
            bounds.height()<=viewport.height()*3/4 && bounds.width()<=viewport.width();
        if((exact || card) && !bounds.isEmpty() && bounds.intersect(viewport)) {
            bounds.inset(-2,-2);
            bounds.intersect(viewport);
            s.regions.clear(); s.regions.add(bounds);
        }
        return s;
    }
    private void addRegion(List<Rect> result,Rect region) {
        // Keep disjoint cards separate; never paint the gap containing ordinary videos.
        for(int i=0;i<result.size();i++) {
            Rect old=result.get(i);
            if(old.contains(region)) return;
            if(region.contains(old)) { result.remove(i--); }
        }
        result.add(new Rect(region));
    }
    private void removeLast() {
        View view=views.remove(views.size()-1);
        try { windows.removeView(view); } catch(RuntimeException ignored) { }
    }
    void clear() {
        while(!views.isEmpty()) removeLast();
        current=new ArrayList<>();
    }
}
