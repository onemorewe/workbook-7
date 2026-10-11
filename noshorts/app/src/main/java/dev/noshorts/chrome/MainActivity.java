package dev.noshorts.chrome;

import android.app.Activity;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.accessibility.AccessibilityManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import dev.noshorts.core.UrlRules;

public final class MainActivity extends Activity {
    private TextView status;
    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ScrollView scroll=new ScrollView(this);
        LinearLayout box=new LinearLayout(this); box.setOrientation(LinearLayout.VERTICAL); box.setPadding(40,60,40,40);
        scroll.addView(box); setContentView(scroll);
        text(box,"NoShorts",30);
        text(box,"Ленты YouTube, Instagram и LinkedIn открываются в Chrome, но их содержимое скрыто. На его месте — персональные послания Пичаи, Цукербергу и Наделле. Поиск, меню, сообщения и вакансии остаются доступны. Shorts заблокированы, их превью скрыты.",18);
        text(box,"Открыть нужное напрямую",22);
        EditText query=new EditText(this); query.setId(R.id.youtube_search); query.setSingleLine(true);
        query.setHint("Что найти на YouTube?"); box.addView(query);
        Button search=button(box,"Найти видео",()->{
            String value=query.getText().toString().trim();
            if(value.isEmpty()) { Toast.makeText(this,"Введи поисковый запрос",Toast.LENGTH_SHORT).show(); return; }
            openChrome(new Uri.Builder().scheme("https").authority("m.youtube.com").path("/results")
                .appendQueryParameter("search_query",value).build());
        }); search.setId(R.id.open_youtube_search);
        button(box,"Сообщения Instagram",()->openChrome(Uri.parse("https://www.instagram.com/direct/inbox/")));
        button(box,"Сообщения LinkedIn",()->openChrome(Uri.parse("https://www.linkedin.com/messaging/")));
        button(box,"Вакансии LinkedIn",()->openChrome(Uri.parse("https://www.linkedin.com/jobs/")));
        status=text(box,"",16);
        status.setId(R.id.service_status);
        button(box,"Включить службу",()->startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        text(box,"Если Android запрещает включение: Настройки → Приложения → NoShorts → ⋮ → Разрешить ограниченные настройки.",14);
        button(box,"Настроить работу в фоне",()->startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)));
        text(box,"Скрыты: рекомендации и посты на главной YouTube; ленты подписок; главная, Explore и Reels Instagram; главная и лента LinkedIn. Страницы открываются без возврата назад. История YouTube, обычные видео, отдельные посты и профили доступны.\nБез таймера и кнопки временного отключения.",16);
        text(box,"Дополнительные блокировки",22);
        text(box,"По одному правилу на строку. Домен блокирует весь сайт; домен/путь — этот раздел. Например: instagram.com/reel",14);
        EditText rules=new EditText(this); rules.setId(R.id.rules_input); rules.setMinLines(4); rules.setGravity(android.view.Gravity.TOP);
        rules.setText(getSharedPreferences("rules",MODE_PRIVATE).getString("extra","")); box.addView(rules);
        Button save=button(box,"Сохранить правила",()->{
            String value=rules.getText().toString();
            try {
                new UrlRules(value);
                getSharedPreferences("rules",MODE_PRIVATE).edit().putString("extra",value).apply();
                Toast.makeText(this,"Правила сохранены",Toast.LENGTH_SHORT).show();
            } catch(IllegalArgumentException ex) { Toast.makeText(this,ex.getMessage(),Toast.LENGTH_LONG).show(); }
        });
        save.setId(R.id.save_rules);
        text(box,"Без интернета, рекламы и истории посещений. Маски используют адреса ссылок, которые отдаёт Chrome. При загрузке и быстрой прокрутке превью могут мелькнуть до обновления маски. Карточки без доступной ссылки и изменения Chrome требуют проверки на телефоне.",14);
    }
    private void openChrome(Uri uri) {
        try { startActivity(new Intent(Intent.ACTION_VIEW,uri).setPackage("com.android.chrome")); }
        catch(RuntimeException ex) { Toast.makeText(this,"Не удалось открыть Chrome",Toast.LENGTH_LONG).show(); }
    }
    @Override public void onResume() {
        super.onResume();
        AccessibilityManager manager=(AccessibilityManager)getSystemService(ACCESSIBILITY_SERVICE);
        boolean enabled=false;
        for(AccessibilityServiceInfo s:manager.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK))
            if(s.getResolveInfo()!=null && getPackageName().equals(s.getResolveInfo().serviceInfo.packageName)) enabled=true;
        status.setText(enabled ? (ShortsService.connected ? "Служба подключена" : "Служба разрешена; ожидается подключение") : "Блокировка не включена: разреши службу в настройках");
    }
    private TextView text(LinearLayout box,String value,int size) {
        TextView view=new TextView(this); view.setText(value); view.setTextSize(size); view.setPadding(0,12,0,12); box.addView(view); return view;
    }
    private Button button(LinearLayout box,String label,Runnable action) {
        Button b=new Button(this); b.setText(label); b.setAllCaps(false); b.setOnClickListener(v->action.run()); box.addView(b);
        return b;
    }
}
