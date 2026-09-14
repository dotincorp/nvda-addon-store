# NVDA Dot Pad Eklenti Kılavuzu

## Özet

Dot Pad için NVDA eklentisi, NVDA’nın Dot Pad üzerinde braille ve dokunsal grafikleri en iyi şekilde görüntülemesini sağlayan araçtır. Bu eklentiyi yüklemeniz gerekir: eklenti olmadan NVDA, Dot Pad’in çok satırlı ve dokunsal grafik özelliklerinden yararlanamaz.

## Why You Need the Add-on

Geleneksel olarak ekran okuyucular braille ekranına tek satırlık metin gönderir. Ekranı kaydırmak, ekranı o satırın bölümlerini gösterecek şekilde yeniden konumlandırır (çünkü bir ekran genellikle bilgisayar ekranındaki görsel bir satırdan çok daha az karakter gösterir) ve ardından imleci belgedeki bir sonraki veya önceki satıra hareket ettirir ve bir sonraki ekranın metin değerini gösterir. Çok satırlı braille ekran dünyasında, ekrana yalnızca bir satır metin göndermek ve bunu ekranın birden fazla satırına sarmak yeterli değildir; bu da potansiyel olarak ekranın geri kalanını boş bırakır. Bunun yerine, ekran okuyucunun ekrana sığabileceği kadar çok paragraf metni alması gerekir. Daha sonra, ekranı kaydırırken, imlecin, sonraki metin alımının, metin içinde ileri veya geri kaydırma yaparak, bir kitap okumak gibi, okuma deneyiminin sürekli olmasını sağlayacak şekilde hareket etmesini sağlamalıdır. Bu, Braille'in, basılı karakterlerle bire bir karşılık gelen bilgisayar braille kodu kullanılarak gösterilip gösterilmediğine veya kullanıcının, bir sembolün birden fazla yazdırma karakterini temsil edebildiği kısaltılmış Braille'i görüntülemeyi seçip seçmediğine bakılmaksızın gerçekleşmelidir. Her iki durumda da, braille ekranındaki bir metin satırına karşılık gelen şey, neredeyse hiçbir zaman ekrandaki aynı yazdırma satırına karşılık gelmeyecektir. Bu sorun çok satırlı braille bağlamında daha da kötüleşiyor. Eklenti, metin alma, biçimlendirme, çeviri ve kaydırma işlemlerini, NVDA ile Dot Pad'de okurken kullanıcı deneyiminin en iyi şekilde gerçekleştirilmesini sağlar.

Bu eklenti ayrıca harflerin, emojilerin ve grafiklerin, braille okuyucusu için anlamlı bir şekilde Dot Pad üzerinde dokunsal görüntüler olarak görüntülenmesini sağlar. Dokunsal grafikler, anlaşılmasını kolaylaştırmak için büyütülebilir, küçültülebilir ve ters çevrilebilir. Microsoft Word’deki matematik denklemleri ve Excel’deki grafikler de otomatik olarak uygun bir dokunsal görüntüye dönüştürülür. Eksenler, işaretler ve etiketler doğru şekilde oluşturulur ve gerektiğinde çevrilir ve biçimlendirilir.

Bu eklenti, braille öğrenimine yardımcı olacak başka modlar da sunar. Optimum bir okuma deneyimi sağlamak için, çok satırlı braille’deki satır sayısının çift aralıklı (5 satır) ayardan 8 satırlık 8-noktalı braille’e ve 10 satırlık 6-noktalı braille’e kadar ayarlanmasına olanak tanır. Ayrıca, basılı yazı veya braille öğrenenler için bir hibrit basılı yazı ve braille modu da mevcuttur; bu modda, kullanıcı bir belgede gezinirken kelimeler hem braille hem de dokunsal basılı harflerle gösterilir.

Son olarak, bu eklenti, öğretmenlerin ve eğitmenlerin Dot Pad’e gönderilen içeriğin bir gösterimini görebilmeleri için ekran üzerinde bir braille görüntüleyici sunar.

## Dot Pad'e Genel Bakış

Dot Pad, Braille metni ve dokunsal grafikleri aynı anda gösterebilen dokunsal bir bilgi ekranıdır. Dot Pad'i gövdesi size doğru aşağıya eğik olacak şekilde konumlandırmalısınız.

### Ekranlar

- Size en yakın Braille okuma satırı, metin çıktısı için yatay bir çerçeve içinde düzenlenmiş 20 Braille hücresinden oluşmaktadır.
- Grafik Görüntüleme Alanı (Çok Satırlı): Hassas dokunsal grafikler ve çok satırlı braille için yoğun şekilde paketlenmiş 300 adet 8 noktalı braille hücresinden oluşan ön taraftaki en büyük alan.

### Dolaşım Düğmeleri

İki ekran arasında soldan sağa doğru düzenlenmiş altı düğme bulacaksınız:

- Sola Kaydır (Üçgen şekilli)
- F1 Fonksiyon Tuşu (Dokunsal göstergeli oval şekil)
- F2 Fonksiyon Tuşu (Oval şekilli)
- F3 Fonksiyon Tuşu (Oval şekilli)
- F4 Fonksiyon Tuşu (Dokunsal göstergeli oval şekil)
- Sağa Kaydır (Üçgen şekilli)

Dokunsal işaretlerin Dot Pad 320A'da değil, yalnızca daha yeni Dot Pad X donanımında bulunduğunu unutmayın.

### Bağlantı Noktaları ve Anahtarlar

- Sol Taraf (Veri Bağlantısı): Dot Pad X üzerinde braille "d" harfiyle etiketlenmiş bir USB-C bağlantı noktası içerir. Bu bağlantı noktası yalnızca ekran okuyuculu ve ürün yazılımı güncellemeli veri bağlantılarına ayrılmıştır ve şarjı desteklemez. NVDA ile iletişim kurmak için USB kablonuzu buraya bağlayın.
- Sağ Taraf (Sadece Şarj): Dot Pad X üzerinde Braille alfabesiyle "p" harfiyle işaretlenmiş, yalnızca güç ve şarj için ayrılmış bir USB-C bağlantı noktasına sahiptir. Güç düğmesini kendinize doğru bulabilirsiniz.

## Dot Pad'i NVDA'ya Bağlama

Dot Pad'i NVDA'ya Bluetooth Düşük Enerji (BLE) üzerinden kablosuz olarak veya kablolu USB-C bağlantısı kullanarak bağlayabilirsiniz. NVDA Dot Pad eklentisi yüklendikten sonra şu adımları izleyin.

### Otomatik Bağlantı

Dot Pad eklentisinin kurulumu sırasında, Dot Pad ekranının otomatik olarak algılanmasını etkinleştirmeniz istenir. Bu soruya “Evet” yanıtını verdiyseniz ve kurulumu tamamlamak için NVDA’yı yeniden başlattıysanız, Dot Pad cihazı bilgisayar açıldığında otomatik olarak bağlanmalıdır. Dot Pad otomatik olarak algılanmazsa, şu adımları izleyin:

1. Bilgisayara bağlı diğer braille ekranlarını kapatın veya bağlantısını kesin.
2. Dot Pad’i açın. USB-C yöntemini kullanıyorsanız, sol taraftaki veri bağlantı noktasını kullandığınızdan emin olun.
3. Braille ekranı seçimi iletişim kutusunu açmak için NVDA+control+a tuşlarına basın.
4. "Otomatik" seçeneğinin seçili olduğundan emin olun. Bu listedeki ilk seçenek olmalıdır.
5. "Otomatik olarak algılanacak görüntüler" listesine gitmek için sekme tuşuna basın.
6. Bu listede “Dot Pad” seçeneğinin işaretli olduğundan emin olun. İşaretli değilse, boşluk tuşunu kullanarak bu seçeneği işaretleyin.
7. Onaylamak için enter tuşuna basın veya "Tamam" düğmesini tıklayın.

Bundan böyle, USB üzerinden veya Bluetooth menzili içinde bulunan tüm Dot Pad’ler otomatik olarak bağlanacaktır. Ne yazık ki, otomatik algılamayı yalnızca USB veya Bluetooth için etkinleştirmek mümkün değildir. Birden fazla Dot Pad’in bulunduğu bir ortamda Bluetooth bağlantısını belirli bir ekrana sabitlemeniz gerekiyorsa, aşağıdaki manuel bağlantı adımlarını izleyin.

Otomatik algılama özelliği kullanıldığında, ekran USB ve Bluetooth arasında otomatik olarak geçiş yapar. USB-C kablosu Dot Pad’in sol bağlantı noktasına takıldıktan birkaç saniye sonra NVDA geçiş yapar ve Dot Pad, Bluetooth bağlantısının kesildiğini onaylamak için titreşecektir. Buna karşılık, USB kablosu çıkarıldıktan sonra NVDA cihaz aramaya başlayacak ve birkaç saniye içinde Bluetooth üzerinden Dot Pad’i algılayacaktır.

### Manuel Bağlantı

1. Dot Pad’i açın. USB-C yöntemini kullanıyorsanız, Dot Pad’i sol taraftaki veri bağlantı noktasına takın. Bluetooth üzerinden bağlanıyorsanız, Dot Pad açıldığında ekranda görüntülenen Dot Pad Bluetooth adının son dört hanesini not alın.
2. NVDA+control+a tuşlarına basarak NVDA'nın braille ekran seçimi iletişim kutusunu açın.
3. Kullanılabilir braille ekranlar listesinden Dot Pad’i seçin.
4. Bağlantı Noktası listesine gitmek için sekme tuşuna basın ve uygun bağlantı noktasını seçin:
    - Bluetooth için: Dot Pad'inizin benzersiz Bluetooth adını seçin.
    - USB için: Uygun USB bağlantı noktasını seçin.
5. Onaylamak için enter tuşuna basın veya Tamam'a tıklayın.

Dot Pad'den gelen fiziksel bir titreşim, bağlantının başarılı olduğunu onaylayacak ve braille çıktısı hemen başlayacaktır.

### Bağlantı Notları

- Otomatik Bağlantı: NVDA'nın braille ayarları altında, otomatik olarak algılanacak ekranlar listesindeki Dot Pad onay kutusunu işaretlerseniz, NVDA, çevrede tanınan herhangi bir etkin Dot Pad'e otomatik olarak bağlanabilir.
- Kablolu Önceliği: NVDA'nın otomatik arama listesinde Dot Pad'i işaretlediyseniz, sistem, kablo her takıldığında dinamik olarak kablolu USB bağlantısına öncelik verecektir.

Bluetooth ve USB üzerinden aynı anda bağlanamayacağınızı unutmayın.

## NVDA'yı Dolaşım Düğmeleriyle Kontrol Etme

Klavyenize dokunmadan Windows'ta gezinmek ve NVDA'yı kontrol etmek için Nokta Tuş Takımı üzerindeki düğmeleri kullanabilirsiniz. Ancak yazmak ve bazı Windows komutları için bilgisayarınızın klavyesini kullanmanız gerekecektir.

Uzun basmak, söz konusu düğmelerin 1,5 saniye veya daha uzun süre basılı tutulması anlamına gelir. NVDA'nın Girdi Hareketleri iletişim kutusunu kullanarak tüm komutların değiştirilebileceğini veya düğme kombinasyonlarına yeni komutlar atanabileceğini unutmayın. Girdi hareketlerini atama konusunda bilgi için lütfen NVDA'nın kendi kullanım kılavuzuna bakın.

### Kaydırma

- Sol Kaydırma Tuşu (Üçgen): 20 hücreli alandaki braille metninde geriye doğru ilerleyin.
- Sağ Kaydırma Tuşu (Üçgen): 20 hücreli alandaki braille metni boyunca ileri doğru kaydırın.
- F1 Key: Scroll back in the multiline braille area, pan the tactile graphic left, show the previous screenful of table columns, or move to the previous chart data point.
- F4 Key: Scroll forward in the multiline braille area, pan the tactile graphic right, show the next screenful of table columns, or move to the next chart data point.
- F2 Key: In a tactile graphic, scroll the graphic up. In a table, show the previous screenful of rows.
- F3 Key: In a tactile graphic, scroll the graphic down. In a table, show the next screenful of rows.

### Çoklu Tuş Komutları

- Left Pan + F1 Key: Move the viewport left a few dots in graphics mode, or one column in table mode.
- Right Pan + F4 Key: Move the viewport right a few dots in graphics mode, or one column in table mode.
- F1+F2: Move the viewport up a few dots in graphics mode, or one row in table mode.
- F3+F4: Move the viewport down a few dots in graphics mode, or one row in table mode.
- F1+F3: Harfi, emojiyi, grafiği veya seçimi dokunsal bir görüntüye dönüştürür. Ekran görüntüsü alma modu için uzun basın.
- F2+F4: When showing a tactile image or a table, return to braille mode.
- F2+F3: When showing a tactile image, zoom in (magnify the image). When no tactile image is showing, this also converts the letter, emoji, graphic or selection to a tactile image. Long press to force table mode, which scans the parent objects for a table.
- F1+F4: Dokunsal bir görüntü gösterirken uzaklaştırın (görüntüyü küçültün).
- F1+F2+F3+F4: Dokunsal bir görüntüyü gösterirken ters çevirin: boşlukların olduğu yerde noktaları, noktaların olduğu yerde boşlukları gösterin.

## NVDA Braille Ayarları

NVDA, braille çeviri motorunu kontrol ederek ekranınızdaki metni Dot Pad için braille verisine dönüştürür. Bu gelişmiş özellikler ve yapısal davranışlar, NVDA’nın braille ayarları üzerinden yönetilir.

### Çift Ekran Ayrımı (Sistem Odak Noktası ve Dolaşım Nesnesi)

Varsayılan olarak NVDA Dot Pad sürücüsü, yazma imlecinizin veya sekme tuşunun bulunduğu sistem odağını takip etmek için tek satırlı 20 hücreli ekranı eşler. Bu arada, çok satırlı 300 hücreli ekran, Dot Pad ayarları panelindeki Çok Satırlı Kaynak ayarına bağlı olarak ya sistem düzeltme işaretinden gelen çok satırlı metni ya da gezgin nesnesinden ve inceleme imlecinden gelen metni gösterir. Bu, çok satırlı metnin tamamını gözden geçirmenize veya görünüme bağlı olarak iki farklı ekran alanına bağımsız olarak aynı anda bakmanıza olanak tanır.

### Braille Bağlantısı (NVDA+kontrol+t)

Bu ayar, hangi imlecin içeriğinin braille cihazınıza aktarılacağını belirler. Dot Pad kullanırken, braille bağlamayı “Sistem Odak Noktası” olarak ayarlamanız önerilir. Bu, odak metni için 20 hücreli ekran ile çok satırlı bağlam için 300 hücreli ekran arasındaki ayrımı doğal bir şekilde pekiştirir.

### İmleci Takip Et Geçişi

NVDA+7 ("Sistem odağını takip et" seçeneğini etkinleştirin) ve NVDA+6 ("Sistem İşaretini Takip Et" seçeneğini etkinleştirin) tuşlarına basarak, çok satırlı grafik ekranınızdaki metni dondurabilirsiniz. Bu, tek satırlı ekranda bir metin düzenleyiciye aktif olarak yazarken, çok satırlı alanda bir web sayfasına veya belgeye referans vermenizi sağlar.

### Yanıp Sönen İmleç

Varsayılan olarak NVDA, Braille imlecini yanıp söndürür. Noktalı tuş takımı hücreleri yavaş yenilenir ve dokunurken hiç güvenilir bir şekilde yenilenmez, bu nedenle yanıp sönen bir imleç pek işe yaramaz. Eklentinin kurulumu sırasında, yanıp sönen imleci kapatıp kapatmayacağınız sorulur. NVDA'nın tüm Braille ekranları için tek bir yanıp sönme ayarı vardır, bu nedenle "Evet" yanıtı, kullandığınız her ekranda yanıp sönmeyi kapatır. Otomatik algılama sorusu gibi, bu da yalnızca bir kez sorulur ve NVDA'nın Braille ayarlarındaki "İmleci yanıp söndür" onay kutusuyla istediğiniz zaman değiştirebilirsiniz.

### Microsoft Excel ve PowerPoint Grafik Dönüştürme

Control+alt+5 veya NVDA'nın öğe listesini (NVDA+f7) kullanarak Excel veya PowerPoint'te bir grafik alanına gittiğinizde, eklenti, grafik verilerini otomatik olarak 300 hücreli çok satırlı grafik ekranda dinamik olarak oluşturulan bir çubuk grafik düzenine dönüştürür.

Diğer grafik türlerinin de çubuk grafik olarak görüntüleneceğini lütfen unutmayın. Bu, yakın zamanda çözmeyi umduğumuz bir sınırlamadır.

### Girdi Hareketlerini Özelleştirme

F1 ile F4 tuşlarının veya kaydırma tuşlarının işlevlerini değiştirmek istiyorsanız, NVDA menüsünden Tercihler > Girdi Hareketleri seçeneğine gidin. Özellik kategorileri altında “Ekle” seçeneğini seçip Dot Pad’de herhangi bir tuş kombinasyonuna basarak bunu yeni bir NVDA komutuna atayabilirsiniz.

## Dokunsal Grafik Kipi

Bu eklenti, Windows ortamına doğrudan kesintisiz, gerçek zamanlı dokunsal grafikler sunmak üzere Dot’un Dokunsal Ekran API kütüphanesini içerir ve görme engelli kullanıcıların sayfa düzeni şekillerini, diyagramları ve biçimlendirme yapısını fiziksel olarak hissetmelerini sağlar.

### Table Mode

When your cursor lands on a table, the 300-cell display switches to a tactile grid: you feel the cell borders and the columns lining up, rather than a run of braille. The 20-cell braille display keeps showing the text of the cell you are on. This works in Microsoft Excel, in tables on web pages, and in tables in documents.

Table mode starts on its own. If you are on a table but the display has not switched, long press F2+F3 to force it: this looks outward from your cursor for a table to show. Press F2+F4 to go back to braille output.

The buttons that move the view over the table are listed under "Button map reference, table mode" below.

### Dokunsal Harf ve Şekil İşleme (Hibrit Mod)

NVDA Ayarları’ndaki Dot Pad ayarları altında yer alan “Baskı ve braille’i birlikte göster (hibrit mod)” seçeneğini etkinleştirdiğinizde, belgeler veya düzenleme kutuları gibi aktif metin imlecinin bulunduğu alanlarda, braille karakterleri yerine grafik moduna benzer şekilde 300 hücrelik alanda dokunsal baskı olarak gerçek fiziksel harf şekilleri gösterilir. NVDA, ayrı 20 hücrelik metin pencerenizde normal braille gösterimini sürdürür.

### Microsoft Word'de Dokunsal Grafikler

Kartezyen grafikleri anında oluşturmak için matematik ifadelerini doğrudan uygulamaların içinde kullanabilirsiniz.

Microsoft Word'de:

1. Standart denklem düzenleyicisini etkinleştirmek için alt+- tuşlarına basın.
2. İstediğiniz ifadeyi yazın. NVDA, matematik çıktı ayarlarınıza göre metnin çıktısını otomatik olarak alacaktır.

Microsoft Word'de matematik grafiklerini göstermek için aşağıdaki örnek ifadeleri yazabilirsiniz:

- Doğrusal fonksiyon: y = x
- İkinci dereceden fonksiyon (parabol): y = x^2
- Karekök fonksiyonu: y = sqrt(x)
- Kübik fonksiyon: y = x^3
- Sinüzoidal fonksiyon (dalga): y = sin(x)
- Rasyonel fonksiyon: y = 1/x

Dot Pad'de matematik grafiklerini görüntülemek için:

1. Belgenizdeki hedef denkleme gitmek için klavyeyi kullanın.
2. İmlecinizi denklemin üzerine getirin ve dokunsal görüntüleyici moduna girmek için Dot Pad F1+F3 tuşlarına basın.
3. Dot Pad'de F2+F3 tuşlarına basarak yakınlaştırın.
4. Dot Pad'de F1+F4 tuşlarına basarak uzaklaştırın.
5. İşlem tamamlandığında, görüntüleyiciyi kapatmak ve standart Braille çıktısına geri dönmek için Noktalı Tuş Takımı'nda F2+F4 tuşlarına basın.

### Dokunsal Baskı Oluşturma

Ayrıca F1+F3 tuşlarına basarak basılı karakterlerin dokunsal temsilini de hissedebilirsiniz. Dot Pad, imlecin bulunduğu karakteri gösterecektir. F2+F3 ile yakınlaştırabilir, F1+F4 ile uzaklaştırabilirsiniz. Dört fonksiyon tuşuna aynı anda basarak dokunsal görüntüyü tersine çevirebilirsiniz.

## Odak Takibi

Grafik modu, Dot Pad’in manuel olarak girilen koordinatlara gerek kalmadan sistem imleci hareketlerini otomatik olarak takip etmesini sağlar. NVDA inceleme imleciniz, örneğin bir web sayfasındaki sanal bir belgeyi incelerken sistem odağından saparsa, eklenti yönünüzü kaybetmemeniz için sınır kutusu görüntüleme moduna geçer.

## Dolaşım Düğmesi Değişiklikleri ve Kaydırma

Düğmelerin işlevlerinin bağlama göre değiştiğini fark edeceksiniz. Sunum iş akışı, imlecinizin hareketine göre fiziksel düğmelerin atamalarını değiştirir.

Braille sunumunun devralınması: Metni düzenlemek için bir ok tuşuna bastığınızda, iş akışınıza müdahale edilmesini önlemek için grafik modundan otomatik olarak çıkılır. Görünüm kaydırma ve yakınlaştırma hareketleri sınırsızdır ve ekranın yerini braille sunumu devralır.

Düğme haritası referansı, standart kip:

- Sol Kaydırma Tuşu (Üçgen): 20 hücreli metin alanında görüntülenen tek satırlık braille metninde geriye doğru ilerleyin.
- Sağ Kaydırma Tuşu (Üçgen): 20 hücreli metin alanında görüntülenen tek satırlık braille metni boyunca ileri doğru kaydırın.
- F1 Tuşu: 300 hücreli çok satırlı alanda geriye doğru kaydırın veya önceki grafik veri noktasına gidin.
- F4 Tuşu: 300 hücreli çok satırlı alanda ileri doğru kaydırın veya bir sonraki grafik veri noktasına geçin.
- F2+F4: Dokunsal görüntüleyiciden standart Braille çıktısına geri döner veya dokunsal nesne şablonu görselleştirme modunu etkinleştirir.
- F1+F3 veya F2+F3: Microsoft Word'de imleç bir harfin, emojinin, grafiğin, metin seçiminin veya matematik denkleminin üzerine getirildiğinde dokunsal grafik moduna geçilir.

Düğme haritası referansı, dokunsal grafik modu. İnceleme kipi açıkça dokunsal grafiklere ayarlandığında, düğme yapılandırması, grafik veya matematiksel denklemin görüntü alanında doğrudan donanımdan gezinmenizi ve işlem yapmanızı sağlayacak şekilde ayarlanır:

- F2+F3: Dokunsal grafiği veya matematik grafiğini yakınlaştırın.
- F1+F4: Dokunsal grafikten veya matematik grafiğinden uzaklaştırın.
- F1 Key: Pan the tactile graphic view one display to the left.
- F4 Key: Pan the tactile graphic view one display to the right.
- F2 Key: Pan the tactile graphic view one display up.
- F3 Key: Pan the tactile graphic view one display down.
- Long press any of the four keys above to jump the view straight to that edge of the graphic: F1 to the left edge, F4 to the right edge, F2 to the top edge, and F3 to the bottom edge.
- Sol Kaydırma + F1 Tuşu: Dokunsal grafik görünümünü birkaç nokta sola kaydırır.
- Sağ Kaydırma + F4 Tuşu: Dokunsal grafik görünümünü birkaç nokta sağa kaydırır.
- F1+F2: Dokunsal grafik görünümünü birkaç nokta yukarı kaydırır.
- F3+F4: Dokunsal grafik görünümünü birkaç nokta aşağı kaydırır.
- Sol Kaydırma + Sağ Kaydırma Tuşları, aynı anda basıldığında: Dokunsal grafik görünümünü varsayılan, ortalanmış sunuma sıfırlayın.

Button map reference, table mode. When a table is shown on the 300-cell display, the buttons move the view over the table. The keys match tactile graphics mode, so the same movements apply in both:

- F1 Key: Show the previous screenful of columns.
- F4 Key: Show the next screenful of columns.
- F2 Key: Show the previous screenful of rows.
- F3 Key: Show the next screenful of rows.
- Long press any of the four keys above to jump straight to that edge of the table: F1 to the first column, F4 to the last column, F2 to the first row, and F3 to the last row. In a spreadsheet, the edges are the last row and column that contain data, not the end of the sheet itself.
- Left Pan + F1 Key: Move the view one column to the left.
- Right Pan + F4 Key: Move the view one column to the right.
- F1+F2: Move the view up one row.
- F3+F4: Move the view down one row.
- F2+F4: Return to braille output. You can keep moving through the cells of the same table in braille. Table mode comes back when you leave for another table, and tactile graphics mode still starts on its own when you move to an image.

Moving the view does not move your cursor unless you ask it to. The "After scrolling a table, move the navigator object" setting in the Dot Pad settings panel can move it to the first or the centre cell of the new view instead. Moving your cursor the other way round does bring the view with it: if you move out of the visible part of the table, the view follows in that direction only, so moving down keeps your place across the row.

## Dot Pad Ekran Görüntüleyici

Dot Pad bağlıyken kullanılabilen ekran üstü braille görüntüleyici sayesinde, gören öğretmenler, iş arkadaşları, arkadaşlar veya aile üyeleri parmaklarınızın altında ne olduğunu görebilir. NVDA Araçlar menüsündeki Dot Pad Ekran Görüntüleyici seçeneğine bakın. Bu seçenek işaretlendiğinde, Dot Pad kullanımdayken hem tek satır hem de ana grafik alanı bilgisayar ekranında gösterilir. Bu, Dot Pad'in yeteneklerinin görme engelli olmayan kişilere gösterilmesi, eğitim veya diğer işbirliği senaryoları için yararlıdır.

Araçlar menüsünden de erişilebilen NVDA braille görüntüleyicinin yalnızca 20 hücreli ekranı gösterdiğini unutmayın. Dot Pad'i kullanırken, NVDA braille görüntüleyiciyi devre dışı bırakmanız ve Dot Pad Ekran Görüntüleyiciyi yalnızca ekranın ekranda görüntülenmesi gerekiyorsa kullanmanız önerilir.

## Yardım Alma

For problems with the add-on, including bugs and feature requests, please use the [issue tracker](https://github.com/dotincorp/nvda-addon-store/issues). An NVDA log at debug level is usually essential: set the logging level in NVDA's Privacy and Security settings, reproduce the problem, then attach the log. Please review the log before attaching it, as logs record window titles and spoken text. Do not attach crash dumps (nvda_crash.dmp) to a public issue: they contain a raw image of NVDA's memory, which can include the contents of documents you had open. If a crash dump is needed, say so in the issue and it will be arranged privately.

For help with the Dot Pad hardware itself, please contact [Dot Inc.](https://dotincorp.com/)

## Lisans

Bu eklenti, GNU Genel Kamu Lisansı sürüm 2 veya sonraki koşulları kapsamında dağıtılmaktadır. Tam metin COPYING.txt dosyasındadır ve birlikte verilen üçüncü taraf bileşenlerin lisansları THIRD_PARTY_NOTICES.md dosyasındadır. Her iki dosya da bu kılavuzla birlikte gönderilir.
